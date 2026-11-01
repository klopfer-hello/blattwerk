"""Plant name resolver (F-PL-1/4), no AI: turns what people type ("Felsenbrine
Obelisk", "Prunus AV. Celeste Säule", "Säulenapfel Sonate") into ranked
(species, Sorte, form) candidates.

How: fold the text (case, umlauts, accents, ®, punctuation) into tokens, take
form words out as a hint (also as prefix: "Säulenapfel"), then for every species
find the best token span for a species name (typos via difflib, abbreviations
as prefixes, genus alone counts less) and the best span for one of its Sorten.
The score is the share of input tokens explained, so "Kupfer-Felsenbirne
Obelisk" prefers the species that explains "Kupfer" over the one that knows the
Sorte. Unexplained rest after a species is kept as `unmatched` (a Sorte the
catalog does not know yet)."""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from blattwerk.seed import Seed

MAX_CHARS = 200
MAX_TOKENS = 12
MAX_RESULTS = 5
SPECIES_MIN = 0.8
CULTIVAR_MIN = 0.75
CULTIVAR_SHORT_MIN = 0.9  # Sorte spans under 5 letters ("opa" ~ "topaz") need near-exact matches
GENUS_WEIGHT = 0.85  # "Malus" alone is likely right, but less than "Malus domestica"
CULTIVAR_ONLY_WEIGHT = 0.9  # "Sonate" alone: Sorte known, species implied
TRAILING_WEIGHT = 0.9  # end of a German name without its leading words
NEW_SORTE_WEIGHT = 0.3  # rest after a species: probably a Sorte we do not know

FORMS = {
    "saeule": "Säule", "saeulen": "Säule", "saeulenform": "Säule", "hochstamm": "Hochstamm",
    "halbstamm": "Halbstamm", "spalier": "Spalier", "spindel": "Spindel", "kuebel": "Kübel",
    "topf": "Kübel", "hecke": "Hecke", "strauch": "Strauch", "stamm": "Stamm",
}  # fmt: skip
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def fold(text: str) -> str:
    """Lower case, umlauts as ae/oe/ue, accents removed, only a-z and 0-9."""
    text = unicodedata.normalize("NFKD", text.lower().translate(_UMLAUTS))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)))


def _words(text: str) -> list[tuple[str, str]]:
    """(folded, display) per word; hyphens and punctuation split words."""
    out = []
    # Phones type en dashes and typographic quotes, hence the escapes below.
    for raw in re.split("[\\s/,;:()\\-\u2013]+", text[:MAX_CHARS]):
        display = raw.strip(".'\u2018\u2019\"\u201e\u201c\u00ae\u2122*")
        token = fold(display)
        if token:
            out.append((token, display))
    return out


@dataclass(frozen=True)
class _Name:
    tokens: tuple[str, ...]
    key: str
    weight: float = 1.0


def _name(text: str, weight: float = 1.0) -> _Name:
    tokens = tuple(t for t, _ in _words(text))
    return _Name(tokens, "".join(tokens), weight)


@dataclass(frozen=True)
class CultivarData:
    id: str
    species_id: str
    name: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpeciesData:
    id: str
    latin: str
    german: tuple[str, ...]
    synonyms: tuple[str, ...] = ()


@dataclass
class _Species:
    data: SpeciesData
    names: list[_Name]
    cultivars: list[tuple[CultivarData, list[_Name]]]


def cultivar_id(species_id: str, name: str) -> str:
    return f"{species_id}:{fold(name)}"


class Catalog:
    def __init__(self, species: Iterable[SpeciesData], cultivars: Iterable[CultivarData]) -> None:
        by_species: dict[str, list[CultivarData]] = {}
        for c in cultivars:
            by_species.setdefault(c.species_id, []).append(c)
        self.species: list[_Species] = []
        for s in species:
            names = [_name(n) for n in (s.latin, *s.german, *s.synonyms)]
            # "Japanischer Blumen-Hartriegel" is also typed as "Blumen-Hartriegel" or "Hartriegel"
            names += [
                _Name(n.tokens[k:], "".join(n.tokens[k:]), TRAILING_WEIGHT)
                for n in [_name(g) for g in (*s.german, *s.synonyms)]
                for k in range(1, len(n.tokens))
            ]
            genus = s.latin.split()[0]
            if " " in s.latin:
                names.append(_name(genus, GENUS_WEIGHT))
            cults = [(c, [_name(n) for n in (c.name, *c.synonyms)]) for c in by_species.get(s.id, [])]
            self.species.append(_Species(s, [n for n in names if n.key], cults))

    @classmethod
    def from_seed(cls, seed: Seed) -> "Catalog":
        species = [SpeciesData(s.id, s.latin, tuple(s.german), tuple(s.synonyms)) for s in seed.species]
        cultivars = [
            CultivarData(cultivar_id(s.id, c.name), s.id, c.name, tuple(c.synonyms))
            for s in seed.species
            for c in s.cultivars
        ]
        return cls(species, cultivars)


@dataclass(frozen=True)
class Candidate:
    species_id: str
    latin: str
    german: str
    cultivar_id: str | None
    cultivar_name: str | None
    unmatched: str
    form_hint: str | None
    score: float


type _Span = tuple[int, int, float]  # start, end (exclusive), score


def _span_score(name: _Name, span: list[str], min_prefix: int = 2) -> float:
    if len(span) == len(name.tokens) and all(
        len(s) >= min_prefix and n.startswith(s) for s, n in zip(span, name.tokens, strict=True)
    ):
        return name.weight * (1.0 if tuple(span) == name.tokens else 0.95)  # exact or abbreviation ("av" → avium)
    return name.weight * SequenceMatcher(None, "".join(span), name.key).ratio()


def _max_span(name: _Name) -> int:
    """A one-word name may be typed as two words ("Rambler Rose" for Ramblerrose);
    longer names never take extra words (they would swallow the Sorte)."""
    return 2 if len(name.tokens) == 1 else len(name.tokens)


def _best_spans(names: list[_Name], tokens: list[str], minimum: float, *, sorte: bool = False) -> list[_Span]:
    """Best score per token span over all names, only spans at or above minimum.
    Sorten are stricter: abbreviations need 3 letters, short spans near-exact."""
    spans = []
    for i in range(len(tokens)):
        for j in range(i + 1, min(len(tokens), i + 5) + 1):
            scores = (_span_score(n, tokens[i:j], 3 if sorte else 2) for n in names if j - i <= _max_span(n))
            best = max(scores, default=0.0)
            if sorte and len("".join(tokens[i:j])) < 5 and best < CULTIVAR_SHORT_MIN:
                continue
            if best >= minimum:
                spans.append((i, j, best))
    return spans


def _tokens(text: str) -> tuple[list[tuple[str, str]], str | None]:
    form = None
    kept = []
    for token, display in _words(text):
        if token in FORMS:
            form = FORMS[token]
            continue
        if token.startswith("saeulen") and len(token) > len("saeulen") + 2:  # "Säulenapfel"
            form = "Säule"
            cut = next(k for k in range(1, len(display) + 1) if fold(display[:k]) == "saeulen")
            token, display = token[len("saeulen") :], display[cut:]
        if len(token) < 2 or token.isdigit():  # "R" for ®, numbers
            continue
        kept.append((token, display))
    return kept[:MAX_TOKENS], form


def resolve(catalog: Catalog, text: str) -> list[Candidate]:
    words, form = _tokens(text)
    tokens = [t for t, _ in words]
    if not tokens:
        return []
    total = len(tokens)
    results: list[Candidate] = []
    for sp in catalog.species:
        species_spans: list[_Span | None] = [*_best_spans(sp.names, tokens, SPECIES_MIN), None]
        cult_spans = {c.id: _best_spans(names, tokens, CULTIVAR_MIN, sorte=True) for c, names in sp.cultivars}
        # best: (score, species span, cultivar span, cultivar)
        best: tuple[float, _Span | None, _Span | None, CultivarData | None] | None = None
        for s in species_spans:
            used = set(range(s[0], s[1])) if s else set()
            options: list[tuple[_Span | None, CultivarData | None]] = [(None, None)]
            for cult, _ in sp.cultivars:
                options += [(cs, cult) for cs in cult_spans[cult.id] if not used & set(range(cs[0], cs[1]))]
            for cs, c in options:
                if s is None and cs is None:
                    continue
                explained = (s[2] * (s[1] - s[0]) if s else 0.0) + (
                    cs[2] * (cs[1] - cs[0]) * (1.0 if s else CULTIVAR_ONLY_WEIGHT) if cs else 0.0
                )
                if cs is None:
                    explained += NEW_SORTE_WEIGHT * (total - (s[1] - s[0] if s else 0))
                score = explained / total
                if best is None or score > best[0]:
                    best = (score, s, cs, c)
        if best is None:
            continue
        score, s, cs, cultivar = best
        covered = set(range(s[0], s[1])) if s else set()
        if cs:
            covered |= set(range(cs[0], cs[1]))
        unmatched = "" if cultivar else " ".join(d for k, (_, d) in enumerate(words) if k not in covered)
        results.append(
            Candidate(
                species_id=sp.data.id,
                latin=sp.data.latin,
                german=sp.data.german[0] if sp.data.german else sp.data.latin,
                cultivar_id=cultivar.id if cultivar else None,
                cultivar_name=cultivar.name if cultivar else None,
                unmatched=unmatched,
                form_hint=form,
                score=round(score, 3),
            )
        )
    results.sort(key=lambda c: (-c.score, c.latin))
    return results[:MAX_RESULTS]
