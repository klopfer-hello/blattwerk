"""AI name suggestions (M5, F-AI-3): when the offline resolver does not know a plant,
Claude suggests species + Sorte candidates for the user to pick from.

Only the typed name is sent. The answer is validated like user input (same rules
as SpeciesIn / CultivarIn); invalid candidates are dropped, never repaired."""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.functional_validators import AfterValidator, BeforeValidator

from blattwerk.claude_cli import ClaudeError
from blattwerk.models import Form, Name60
from blattwerk.seed import Growth

PROMPT_VERSION = "names-3"
MAX_CANDIDATES = 5
FORMS: tuple[str, ...] = Form.__args__  # type: ignore[attr-defined]

SYSTEM = """Du bestimmst Garten- und Zimmerpflanzen aus dem, was jemand eintippt oder fotografiert: deutsche oder
lateinische Namen, Abkürzungen, Handelsnamen, Tippfehler, oft mit Sorte und Wuchsform (z. B. "Prunus AV. Celeste
Säule", "Felsenbrine Obelisk").
Antworte ausschließlich im vorgegebenen JSON-Format.

- Bis zu 5 Kandidaten, der wahrscheinlichste zuerst. Kein Kandidat, wenn du es nicht weißt.
- "latin": botanischer Name der Art (Gattung + Art, Hybriden mit \u00d7), ohne Sorte und ohne Autor.
  Bei Sorten ohne klare Art (z. B. Rosen) nur die Gattung ("Rosa").
- "german": 1-3 übliche deutsche Namen. "family": Pflanzenfamilie (lateinisch).
- "growth": baum, strauch, hecke, kletterpflanze, kuebel, staude, gras, knolle, gemuese, kraut oder einjaehrig.
  "woody": true für Gehölze (Bäume, Sträucher, Rosen, Kletterer mit Holz).
- "cultivar": Sortenname ohne Anführungszeichen und ohne ®/™, in der offiziellen Schreibweise; null, wenn keine
  Sorte genannt ist. Tippfehler in bekannten Sortennamen korrigieren (z. B. "Elstaar" -> "Elstar", "Topas" ->
  "Topaz"); ein einzelnes "R" oder "(R)" nach dem Namen steht meist für ®. Erfinde keine Sorten: ist die Sorte dir
  wirklich unbekannt, übernimm die Schreibweise und sag es in "note".
- "form_hint": Säule, Halbstamm, Hochstamm, Busch, Spindel, Spalier, Strauch, Hecke, Solitär, Kübel, Kletterer,
  Horst oder Knolle, wenn die Eingabe eine Form nennt; sonst null.
- "winterhaerte_c": tiefste Temperatur in °C, die eine eingewachsene Pflanze ausgepflanzt übersteht (z. B. -25
  für Apfel, -5 für Oleander, 2 für Tomate); null, wenn unklar.
- "note": höchstens ein kurzer Satz (z. B. "Säulenkirsche, selbstfruchtbar"), sonst leer."""


def _clean_cultivar(v: object) -> object:
    if not isinstance(v, str):
        return v
    return v.strip().strip("'\u2018\u2019\"\u201e\u201c\u201d").replace("®", "").replace("™", "").strip()


# Genus, optionally epithet (hybrids with \u00d7) and subsp./var.: "Rosa", "Prunus avium", "Allium ampeloprasum var.
# porrum". Sorten, authors ("L.") and odd case are rejected: the name becomes master data and the species id.
LATIN = re.compile(r"[A-Z][a-z]+(?: (?:\u00d7 )?[a-z][a-z-]+(?: (?:subsp|var)\. [a-z][a-z-]+)?)?")


def _latin(v: str) -> str:
    v = " ".join(v.split())
    if not LATIN.fullmatch(v):
        raise ValueError("not a botanical name")
    return v


def clamp_hardiness(v: object) -> int | None:
    """A hardiness from the AI: rounded and clamped to -45..15 °C; anything odd counts as unknown."""
    try:
        return None if v is None else max(-45, min(15, round(float(v))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


Latin = Annotated[str, Field(min_length=3, max_length=80), AfterValidator(_latin)]


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latin: Latin
    german: Annotated[list[Name60], Field(min_length=1, max_length=5)]
    family: Annotated[str | None, Field(max_length=60, pattern="^[A-Za-z]+$")] = None
    growth: Growth
    woody: bool
    cultivar: Annotated[Name60 | None, BeforeValidator(_clean_cultivar)] = None
    form_hint: Form | None = None
    winterhaerte_c: Annotated[int | None, BeforeValidator(clamp_hardiness)] = None
    note: Annotated[str, Field(max_length=200)] = ""


class _SchemaCandidate(BaseModel):
    latin: Annotated[str, Field(max_length=80)]
    german: list[Annotated[str, Field(max_length=60)]]
    family: Annotated[str, Field(max_length=60)] | None
    growth: Literal["baum", "strauch", "hecke", "kletterpflanze", "kuebel", "staude", "gras", "knolle", "gemuese",
                    "kraut", "einjaehrig"]  # fmt: skip
    woody: bool
    cultivar: Annotated[str, Field(max_length=60)] | None
    form_hint: str | None
    winterhaerte_c: int | None
    note: Annotated[str, Field(max_length=200)]


class _SchemaAnswer(BaseModel):
    candidates: list[_SchemaCandidate]


SCHEMA: dict[str, Any] = _SchemaAnswer.model_json_schema()


def build_prompt(query: str, photos: int = 0) -> str:
    if photos:  # plant ID by photo (M11): the photos come as image blocks
        hint = f"\nHinweis des Nutzers: {query}" if query else ""
        return (f"Welche Pflanze ist auf dem Foto{'s' if photos == 1 else ''} zu sehen? Bestimme die Art (und die "
                f"Sorte nur, wenn sie eindeutig erkennbar ist); in \"note\" wie sicher du bist.{hint}")  # fmt: skip
    return f"Welche Pflanze ist gemeint?\nEingabe: {query}"


def sanitize(raw: dict[str, Any]) -> list[Suggestion]:
    items = raw.get("candidates") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ClaudeError("Die KI-Antwort war unvollständig. Bitte nochmal versuchen.")
    out: list[Suggestion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("form_hint") not in FORMS:
            item = item | {"form_hint": None}  # a wrong hint is not worth losing the candidate
        try:
            out.append(Suggestion.model_validate(item))
        except ValidationError:
            continue
        if len(out) == MAX_CANDIDATES:
            break
    return out
