"""Legal rule engine (requirements 03-legal, law text verified 2026-10-31). Pure.

The AI proposes tasks (M5) and people write their own; this module decides,
deterministically, what the law and the ecological defaults say about them:
- §39 Abs. 5 Nr. 2 BNatSchG: 1.3.-30.9. no strong cutting of hedges, living
  fences, shrubs and other woody plants. Trees in gardens are not covered
  ("gärtnerisch genutzte Grundflächen"). Gentle form and care cuts are allowed.
  Strong cuts are clipped to the allowed part of their window or moved to the
  month after the period; the same rule applies to postponing (routes.todos).
  The states may extend or shift the period by up to two weeks: CLOSED_PERIOD
  holds deviations per Bundesland (none entered yet, see /law-review).
- §44 Abs. 1 BNatSchG: all year, no harm to nests and protected animals.
- Baumschutzsatzung of the municipality (threshold from the settings).
- Ecological default: grasses and perennials stand until early spring.
Unknown cases are handled conservatively (no plant: assume covered)."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

PARA39 = "§ 39 Abs. 5 Nr. 2 BNatSchG"
PARA44 = "§ 44 Abs. 1 BNatSchG"
BAUMSCHUTZ = "Baumschutzsatzung der Gemeinde"
FEDERAL_PERIOD = ((3, 1), (9, 30))  # (month, day) from, to; inclusive
CLOSED_PERIOD: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {}  # Bundesland: own period, when known
MONTH_NAMES = [
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]
SUMMER = frozenset(range(3, 10))  # months touched by the federal closed period
AUTUMN = frozenset({9, 10, 11, 12})
# Explicit fruit species (review M4): ornamental Prunus/Malus, walnut and sweet chestnut are often NOT exempt
# in Baumschutzsatzungen, so they are treated as protected trees (conservative).
FRUIT_SPECIES = {
    "Malus domestica",
    "Pyrus communis",
    "Prunus avium",
    "Prunus cerasus",
    "Prunus domestica",
    "Cydonia oblonga",
    "Mespilus germanica",
}


@dataclass(frozen=True)
class PlantFacts:
    woody: bool
    growth: str
    fruit_tree: bool
    girth_cm: int | None
    indoor: bool = False  # a Zimmerpflanze (M11): § 39 and the tree bylaws are about the garden


@dataclass(frozen=True)
class LegalSettings:
    bundesland: str | None
    baumschutz_girth_cm: int | None
    fruit_trees_exempt: bool
    eco_defaults: bool


@dataclass(frozen=True)
class Note:
    code: str
    severity: Literal["info", "warn"]
    text: str
    ref: str


@dataclass(frozen=True)
class Adjusted:
    due_from: date
    due_to: date
    kind: Literal["moved", "clipped"] | None
    reason: str


def is_fruit_tree(latin: str, growth: str) -> bool:
    return growth == "baum" and latin in FRUIT_SPECIES


def _covered(plant: PlantFacts | None) -> bool:
    """§39 covers woody plants that are not garden trees (outdoors); unknown plant: assume covered."""
    return plant is None or (not plant.indoor and plant.woody and plant.growth != "baum")


def _strong(category: str, cut_type: str | None, plant: PlantFacts | None) -> bool:
    return category == "schnitt" and cut_type == "stark" and _covered(plant)


def _closed(year: int, bundesland: str | None) -> tuple[date, date]:
    (m1, d1), (m2, d2) = CLOSED_PERIOD.get(bundesland or "", FEDERAL_PERIOD)
    return date(year, m1, d1), date(year, m2, d2)


def _period_text(s: LegalSettings) -> str:
    start, end = _closed(2001, s.bundesland)
    return f"vom {start.day}. {MONTH_NAMES[start.month]} bis {end.day}. {MONTH_NAMES[end.month]}"


def _month_end(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def adjust_window(
    category: str, cut_type: str | None, plant: PlantFacts | None, s: LegalSettings, due_from: date, due_to: date
) -> Adjusted:
    """The first allowed stretch of a strong cut's window, else the month after the closed period."""
    if not _strong(category, cut_type, plant):
        return Adjusted(due_from, due_to, None, "")
    parts = [(due_from, due_to)]
    for year in range(due_from.year, due_to.year + 1):
        start, end = _closed(year, s.bundesland)
        parts = [
            piece
            for a, b in parts
            for piece in ((a, min(b, start - timedelta(days=1))), (max(a, end + timedelta(days=1)), b))
            if piece[0] <= piece[1]
        ]
    if parts and parts[0] == (due_from, due_to):
        return Adjusted(due_from, due_to, None, "")
    rule = f"starker Rückschnitt von Hecken, Sträuchern und Gehölzen ist {_period_text(s)} verboten ({PARA39})"
    if parts:
        return Adjusted(parts[0][0], parts[0][1], "clipped", f"Zeitraum gekürzt: {rule}.")
    first = _closed(due_from.year, s.bundesland)[1] + timedelta(days=1)
    return Adjusted(first, _month_end(first), "moved", f"Verschoben auf die Zeit danach: {rule}.")


def blocked_until(
    category: str, cut_type: str | None, plant: PlantFacts | None, s: LegalSettings, day: date
) -> date | None:
    """For an open strong cut: the first allowed day if `day` lies in the closed period."""
    adj = adjust_window(category, cut_type, plant, s, day, day)
    return adj.due_from if adj.kind else None


def notes(
    category: str, cut_type: str | None, plant: PlantFacts | None, s: LegalSettings, months: frozenset[int]
) -> list[Note]:
    """What to tell the gardener about a task due in `months`."""
    if category != "schnitt" or (plant is not None and plant.indoor):
        return []
    out: list[Note] = []
    if _strong(category, cut_type, plant):
        out.append(
            Note(
                "para39-strong",
                "warn",
                f"Starker Rückschnitt nicht {_period_text(s)} (Vogelschutzzeit). In dieser Zeit nur "
                "schonende Form- und Pflegeschnitte.",
                PARA39,
            )
        )
        out.append(
            Note(
                "para39-state",
                "info",
                "Die Bundesländer dürfen diese Zeit verlängern oder um bis zu zwei Wochen verschieben. "
                "Im Zweifel bei der unteren Naturschutzbehörde nachfragen.",
                "§ 39 Abs. 5 BNatSchG",
            )
        )
    elif cut_type == "pflege" and _covered(plant) and months & SUMMER:
        out.append(
            Note(
                "para39-gentle",
                "info",
                "Schonender Form- und Pflegeschnitt: nach § 39 auch in der Vogelschutzzeit erlaubt, "
                "wenn keine Nester oder Tiere betroffen sind (siehe § 44).",
                PARA39,
            )
        )
    out.append(
        Note(
            "para44",
            "info",
            "Vorher auf Nester, brütende Vögel und Tiere (z. B. Igel, Fledermäuse) prüfen. Sie dürfen "
            "nicht gestört oder beschädigt werden.",
            PARA44,
        )
    )
    tree = cut_type == "stark" and plant is not None and plant.growth == "baum"
    if tree and not s.baumschutz_girth_cm:
        out.append(
            Note(
                "baumschutz-unknown",
                "info",
                "Vor starkem Rückschnitt oder Fällen prüfen, ob die Gemeinde eine Baumschutzsatzung hat "
                "(dann in den Einstellungen eintragen).",
                BAUMSCHUTZ,
            )
        )
    elif tree and plant is not None and s.baumschutz_girth_cm:
        if plant.girth_cm is None:
            out.append(
                Note(
                    "baumschutz-girth",
                    "info",
                    "Stammumfang beim Baum eintragen, dann prüft die App die Baumschutzsatzung.",
                    BAUMSCHUTZ,
                )
            )
        elif plant.girth_cm >= s.baumschutz_girth_cm and not (plant.fruit_tree and s.fruit_trees_exempt):
            out.append(
                Note(
                    "baumschutz",
                    "warn",
                    f"Stammumfang {plant.girth_cm} cm (geschützt ab {s.baumschutz_girth_cm} cm): starken "
                    "Rückschnitt oder Fällen vorher bei der Gemeinde genehmigen lassen.",
                    BAUMSCHUTZ,
                )
            )
    if s.eco_defaults and plant is not None and plant.growth in ("gras", "staude") and months & AUTUMN:
        out.append(
            Note(
                "eco-stand",
                "info",
                "Ökologische Empfehlung: Halme und Samenstände bis zum Vorfrühling stehen lassen. Sie "
                "sind Winterquartier und Futter für Insekten und Vögel.",
                "Ökologische Voreinstellung",
            )
        )
    return out


def allowed_months(
    category: str, cut_type: str | None, plant: PlantFacts | None, s: LegalSettings, months: list[int]
) -> tuple[list[int], set[int]]:
    """Calendar view, consistent with adjust_window: `months` in window order (a yearly window
    Nov-Feb as [11, 12, 1, 2]); keeps the first allowed stretch, else the month after the closed
    period. Returns the months and those that only appear because of a move."""
    if not _strong(category, cut_type, plant) or not months:
        return months, set()
    start, end = _closed(2001, s.bundesland)  # month granularity is enough for the calendar
    closed = set(range(start.month, end.month + 1))
    stretch: list[int] = []
    for m in months:
        if m in closed:
            if stretch:
                break
            continue
        stretch.append(m)
    if stretch:
        return stretch, set()
    after = (end + timedelta(days=1)).month
    return [after], {after}
