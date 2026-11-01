"""Name resolver (F-PL-1/4): German or Latin input, typos, abbreviations, form
words and trade marks → ranked (species, Sorte, form) candidates. Pure, no DB."""

import pytest

from blattwerk.resolver import Catalog, resolve
from blattwerk.seed import load_seed


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog.from_seed(load_seed())


# The household's real plants (requirements F-PL-1) plus typical inputs.
CASES = [
    ("Prunus AV. Celeste Säule", "Prunus avium", "Celeste", "Säule"),
    ("Malus Rapsodi R Säule", "Malus domestica", "Rhapsodie", "Säule"),
    ("Säulenapfel Sonate", "Malus domestica", "Sonate", "Säule"),
    ("Felsenbrine Obelisk", "Amelanchier alnifolia", "Obelisk", None),
    ("Rambler Rose Ghislaine DE Feligonde", "Rosa", "Ghislaine de Féligonde", None),
    ("Ruten-Hirse Heavy Metal", "Panicum virgatum", "Heavy Metal", None),
    ("Chinaschilf", "Miscanthus sinensis", None, None),
    ("Schöner aus Boskoop", "Malus domestica", "Boskoop", None),
    ("Sonate", "Malus domestica", "Sonate", None),
    ("Hortensie Annabelle", "Hydrangea arborescens", "Annabelle", None),
    ("tomate", "Solanum lycopersicum", None, None),
    ("Thuja Smaragd Hecke", "Thuja occidentalis", "Smaragd", "Hecke"),
]


@pytest.mark.parametrize(("text", "latin", "cultivar", "form"), CASES)
def test_resolves_to_expected_top_candidate(
    catalog: Catalog, text: str, latin: str, cultivar: str | None, form: str | None
) -> None:
    top = resolve(catalog, text)[0]
    assert (top.latin, top.cultivar_name, top.form_hint) == (latin, cultivar, form)


def test_unknown_cultivar_text_is_kept_for_the_user(catalog: Catalog) -> None:
    top = resolve(catalog, "Kupfer-Felsenbirne Obelisk")[0]
    assert top.latin == "Amelanchier lamarckii"
    assert top.cultivar_id is None
    assert top.unmatched == "Obelisk"


def test_typo_ranks_known_cultivar_first_then_other_species(catalog: Catalog) -> None:
    latins = [c.latin for c in resolve(catalog, "Felsenbrine Obelisk")]
    assert latins[0] == "Amelanchier alnifolia"
    assert "Amelanchier lamarckii" in latins[1:]


@pytest.mark.parametrize("text", ["", "   ", "xyzqwv", "®", "1234"])
def test_nonsense_gives_no_candidates_not_an_error(catalog: Catalog, text: str) -> None:
    assert resolve(catalog, text) == []


def test_at_most_five_candidates_sorted_by_score(catalog: Catalog) -> None:
    cands = resolve(catalog, "Prunus")
    assert 1 < len(cands) <= 5
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)


def test_long_input_is_bounded(catalog: Catalog) -> None:
    assert resolve(catalog, "Apfel " * 500)[0].latin == "Malus domestica"


@pytest.mark.parametrize("text", ["Apfel von Opa", "Kirsche la", "Apfel ga"])
def test_short_words_do_not_invent_a_sorte(catalog: Catalog, text: str) -> None:
    assert resolve(catalog, text)[0].cultivar_id is None


def test_saeulen_prefix_keeps_the_rest_intact(catalog: Catalog) -> None:
    top = resolve(catalog, "Saeulenapfel Neuzucht")[0]
    assert (top.latin, top.form_hint, top.unmatched) == ("Malus domestica", "Säule", "Neuzucht")
