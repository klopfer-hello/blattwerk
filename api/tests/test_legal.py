"""Legal rule engine (requirements 03-legal, verified 2026-10-31): pure, table-driven."""

from datetime import date

import pytest

from garten_planer.legal import LegalSettings, PlantFacts, adjust_window, is_fruit_tree, notes

D = date
HEDGE = PlantFacts(woody=True, growth="hecke", fruit_tree=False, girth_cm=None)
SHRUB = PlantFacts(woody=True, growth="strauch", fruit_tree=False, girth_cm=None)
OAK = PlantFacts(woody=True, growth="baum", fruit_tree=False, girth_cm=120)
APPLE = PlantFacts(woody=True, growth="baum", fruit_tree=True, girth_cm=120)
GRASS = PlantFacts(woody=False, growth="gras", fruit_tree=False, girth_cm=None)
S = LegalSettings(bundesland="Sachsen", baumschutz_girth_cm=80, fruit_trees_exempt=True, eco_defaults=True)


def codes(cat: str, cut: str | None, plant: PlantFacts | None, months: set[int], s: LegalSettings = S) -> set[str]:
    return {n.code for n in notes(cat, cut, plant, s, frozenset(months))}


# ----- §39: which windows are allowed -------------------------------------------


@pytest.mark.parametrize(
    ("plant", "window", "expected"),
    [
        # strong cut of a hedge in June: nothing allowed -> moved to October
        (HEDGE, (D(2026, 6, 1), D(2026, 6, 30)), (D(2026, 10, 1), D(2026, 10, 31), "moved")),
        # Feb-Apr: only February stays
        (HEDGE, (D(2026, 2, 1), D(2026, 4, 30)), (D(2026, 2, 1), D(2026, 2, 28), "clipped")),
        # Sep-Nov: October and November stay
        (SHRUB, (D(2026, 9, 1), D(2026, 11, 30)), (D(2026, 10, 1), D(2026, 11, 30), "clipped")),
        # across the year end, entirely allowed
        (HEDGE, (D(2026, 11, 1), D(2027, 2, 28)), (D(2026, 11, 1), D(2027, 2, 28), None)),
        # across the year end into March: clipped at the end of February
        (HEDGE, (D(2026, 11, 1), D(2027, 3, 31)), (D(2026, 11, 1), D(2027, 2, 28), "clipped")),
        (HEDGE, (D(2027, 9, 30), D(2027, 9, 30)), (D(2027, 10, 1), D(2027, 10, 31), "moved")),  # last forbidden day
        (HEDGE, (D(2028, 2, 29), D(2028, 2, 29)), (D(2028, 2, 29), D(2028, 2, 29), None)),  # leap day is allowed
        # garden trees are not covered by §39 (gärtnerisch genutzte Grundfläche)
        (OAK, (D(2026, 6, 1), D(2026, 6, 30)), (D(2026, 6, 1), D(2026, 6, 30), None)),
        (APPLE, (D(2026, 6, 1), D(2026, 6, 30)), (D(2026, 6, 1), D(2026, 6, 30), None)),
        # garden-wide task (no plant): treated as covered, to be safe
        (None, (D(2026, 6, 1), D(2026, 6, 30)), (D(2026, 10, 1), D(2026, 10, 31), "moved")),
    ],
)
def test_strong_cut_window(
    plant: PlantFacts | None, window: tuple[date, date], expected: tuple[date, date, str | None]
) -> None:
    got = adjust_window("schnitt", "stark", plant, S, *window)
    assert (got.due_from, got.due_to, got.kind) == expected
    if got.kind:
        assert "§ 39" in got.reason


@pytest.mark.parametrize(
    ("cat", "cut", "plant"),
    [("schnitt", "pflege", HEDGE), ("duengen", None, HEDGE), ("schnitt", "stark", GRASS), ("winterschutz", None, None)],
)
def test_other_tasks_are_never_moved(cat: str, cut: str | None, plant: PlantFacts | None) -> None:
    got = adjust_window(cat, cut, plant, S, D(2026, 6, 1), D(2026, 6, 30))
    assert (got.due_from, got.due_to, got.kind, got.reason) == (D(2026, 6, 1), D(2026, 6, 30), None, "")


# ----- notes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cat", "cut", "plant", "months", "expected"),
    [
        ("schnitt", "stark", HEDGE, {2}, {"para39-strong", "para39-state", "para44"}),
        ("schnitt", "pflege", HEDGE, {6}, {"para39-gentle", "para44"}),
        ("schnitt", "pflege", HEDGE, {11}, {"para44"}),  # outside the season nothing to say about §39
        ("schnitt", "stark", OAK, {6}, {"para44", "baumschutz"}),  # 120 cm >= 80 cm
        ("schnitt", "stark", APPLE, {6}, {"para44"}),  # fruit trees exempt
        ("schnitt", "pflege", OAK, {6}, {"para44"}),  # gentle cut: no permit needed
        ("schnitt", "stark", GRASS, {10}, {"para44", "eco-stand"}),
        ("schnitt", "stark", GRASS, {3}, {"para44"}),  # spring cut is what we recommend
        ("duengen", None, HEDGE, {3}, set()),
        ("ernte", None, APPLE, {9}, set()),
    ],
)
def test_notes(cat: str, cut: str | None, plant: PlantFacts, months: set[int], expected: set[str]) -> None:
    assert codes(cat, cut, plant, months) == expected


def test_baumschutz_needs_threshold_and_knows_missing_girth() -> None:
    unknown = PlantFacts(woody=True, growth="baum", fruit_tree=False, girth_cm=None)
    assert "baumschutz-girth" in codes("schnitt", "stark", unknown, {6})
    no_rule = LegalSettings(bundesland=None, baumschutz_girth_cm=None, fruit_trees_exempt=True, eco_defaults=True)
    assert codes("schnitt", "stark", OAK, {6}, no_rule) == {"para44", "baumschutz-unknown"}
    not_exempt = LegalSettings(
        bundesland="Sachsen", baumschutz_girth_cm=80, fruit_trees_exempt=False, eco_defaults=True
    )
    assert "baumschutz" in codes("schnitt", "stark", APPLE, {6}, not_exempt)


def test_eco_hint_can_be_switched_off() -> None:
    off = LegalSettings(bundesland=None, baumschutz_girth_cm=None, fruit_trees_exempt=True, eco_defaults=False)
    assert codes("schnitt", "stark", GRASS, {10}, off) == {"para44"}


def test_notes_are_german_with_references() -> None:
    [n39] = [n for n in notes("schnitt", "stark", HEDGE, S, frozenset({2})) if n.code == "para39-strong"]
    assert n39.severity == "warn" and n39.ref == "§ 39 Abs. 5 Nr. 2 BNatSchG"
    assert "vom 1. März bis 30. September" in n39.text  # derived from the period, not hard-coded


@pytest.mark.parametrize(
    ("latin", "growth", "expected"),
    [
        ("Malus domestica", "baum", True),
        ("Prunus avium", "baum", True),
        ("Pyrus communis", "baum", True),
        ("Prunus laurocerasus", "strauch", False),  # cherry laurel is no fruit tree
        ("Fagus sylvatica", "hecke", False),
        ("Juglans regia", "baum", False),  # walnut: often not exempt in Baumschutzsatzungen
        ("Prunus serrulata", "baum", False),  # ornamental cherry
    ],
)
def test_fruit_tree(latin: str, growth: str, expected: bool) -> None:
    assert is_fruit_tree(latin, growth) is expected
