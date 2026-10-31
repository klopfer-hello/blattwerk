"""Weather alert rules (M6b, F-WX-4, decided in G-11). Pure: forecast hours in,
events and actions out; wetterwacht does the IO.

Events within the next 48 h, at most one per kind and local day:
- strong_frost: air ≤ -10 °C, any time of year
- frost: air ≤ -2 °C outside the season where frost is expected (Nov-Mar)
- late_frost: from 15 April to the end of May (blossom; until M7 knows the real
  Vollfrühling) air ≤ 0 °C or ground ≤ -1 °C
- heat: air ≥ 32 °C; storm: gusts ≥ 75 km/h
An active alert only ends when the forecast is clearly better (hysteresis, so a
value near the threshold does not flap). Actions never include watering (F-CP-6)."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from garten_planer.legal import FRUIT_SPECIES

LEAD = timedelta(hours=48)
FROST, STRONG_FROST, LATE_FROST_AIR, LATE_FROST_GROUND = -2.0, -10.0, 0.0, -1.0
HEAT, STORM = 32.0, 75.0
FROST_EXPECTED = {11, 12, 1, 2, 3}
LABELS = {"frost": "Frost", "strong_frost": "Strenger Frost", "late_frost": "Spätfrost", "heat": "Hitze",
          "storm": "Sturm"}  # fmt: skip
FROST_KINDS = ("strong_frost", "frost", "late_frost")
TZ = ZoneInfo("Europe/Berlin")
MINUS = chr(0x2212)  # typographic minus sign in "-3,5 °C"


@dataclass(frozen=True)
class Hour:
    time: datetime
    t_air: float | None
    t_ground: float | None
    gust: float | None


@dataclass
class Day:
    air_min: float | None = None
    air_max: float | None = None
    ground_min: float | None = None
    gust_max: float | None = None
    hours: list[Hour] = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    kind: str
    day: date
    value: float  # the extreme: °C for frost/heat, km/h for storm
    first: datetime  # first hour over the threshold: the action is due before it


@dataclass(frozen=True)
class PlantInfo:
    id: str
    title: str
    in_container: bool
    growth: str
    standort_type: str
    latin: str


@dataclass(frozen=True)
class Action:
    key: str
    title: str
    instructions: str
    plant_ids: list[str]


def _min(a: float | None, b: float | None) -> float | None:
    return b if a is None else a if b is None else min(a, b)


def _max(a: float | None, b: float | None) -> float | None:
    return b if a is None else a if b is None else max(a, b)


def daily(hours: list[Hour], now: datetime, night: bool = False) -> dict[date, Day]:
    """Extremes per local day for the hours from now to now + 48 h. With `night`, a day
    runs from noon to noon and is named after its morning: frost from 21:00 to 04:00
    is one event, "the night to Thursday"."""
    days: dict[date, Day] = defaultdict(Day)
    shift = timedelta(hours=12) if night else timedelta(0)
    for h in hours:
        if not now - timedelta(hours=1) <= h.time <= now + LEAD:
            continue
        d = days[(h.time.astimezone(now.tzinfo) + shift).date()]
        d.air_min, d.air_max = _min(d.air_min, h.t_air), _max(d.air_max, h.t_air)
        d.ground_min, d.gust_max = _min(d.ground_min, h.t_ground), _max(d.gust_max, h.gust)
        d.hours.append(h)
    return dict(days)


def _late_frost_season(d: date) -> bool:
    return (d.month == 4 and d.day >= 15) or d.month == 5


def _frost(day: date, s: Day) -> tuple[str, float] | None:
    air, ground = s.air_min, s.ground_min
    if air is not None and air <= STRONG_FROST:
        return "strong_frost", air
    if _late_frost_season(day):
        if (air is not None and air <= LATE_FROST_AIR) or (ground is not None and ground <= LATE_FROST_GROUND):
            return "late_frost", min(v for v in (air, ground) if v is not None)
        return None
    if day.month not in FROST_EXPECTED and air is not None and air <= FROST:
        return "frost", air
    return None


def _first(s: Day, hit: Callable[[Hour], bool]) -> datetime:
    return next((h.time for h in sorted(s.hours, key=lambda h: h.time) if hit(h)), s.hours[0].time)


def detect(hours: list[Hour], now: datetime) -> list[Event]:
    events = []
    for day, s in sorted(daily(hours, now, night=True).items()):
        if found := _frost(day, s):
            kind, value = found
            limit = {"strong_frost": STRONG_FROST, "frost": FROST, "late_frost": LATE_FROST_AIR}[kind]

            def cold(h: Hour, limit: float = limit, kind: str = kind) -> bool:
                ground_hit = kind == "late_frost" and h.t_ground is not None and h.t_ground <= LATE_FROST_GROUND
                return (h.t_air is not None and h.t_air <= limit) or ground_hit

            events.append(Event(kind, day, value, _first(s, cold)))
    for day, s in sorted(daily(hours, now).items()):
        if s.air_max is not None and s.air_max >= HEAT:
            events.append(Event("heat", day, s.air_max, _first(s, lambda h: (h.t_air or -99) >= HEAT)))
        if s.gust_max is not None and s.gust_max >= STORM:
            events.append(Event("storm", day, s.gust_max, _first(s, lambda h: (h.gust or 0) >= STORM)))
    return events


def family(kind: str) -> str:
    """Frost, strong frost and late frost of one night are one alert whose kind can change."""
    return "frost" if kind in FROST_KINDS else kind


def window(kind: str, day: date) -> tuple[datetime, datetime]:
    """When the event can happen: frost from noon before to noon of its morning, else the day."""
    if kind in FROST_KINDS:
        start = datetime.combine(day - timedelta(days=1), datetime.min.time(), TZ) + timedelta(hours=12)
        return start, start + timedelta(days=1)
    start = datetime.combine(day, datetime.min.time(), TZ)
    return start, start + timedelta(days=1)


def all_clear(kind: str, day: date, s: Day | None, now: datetime) -> bool:
    """Clearly better and still ahead: only before the window starts, and only when the
    forecast covers the whole window (a half-covered day says nothing about the rest)."""
    start, end = window(kind, day)
    if s is None or now >= start or end > now + LEAD:
        return False
    if kind in FROST_KINDS:  # the family clears by the rule of the season, not of the last kind
        kind = "late_frost" if _late_frost_season(day) else "strong_frost" if day.month in FROST_EXPECTED else "frost"
    return cleared(kind, s)


def cleared(kind: str, s: Day | None) -> bool:
    """The forecast for that day is clearly better."""
    if s is None:
        return False  # no forecast for the day (yet): keep the alert
    if kind == "strong_frost":
        return s.air_min is not None and s.air_min > STRONG_FROST + 1
    if kind == "frost":
        return s.air_min is not None and s.air_min > FROST + 1
    if kind == "late_frost":
        return (s.air_min is None or s.air_min > LATE_FROST_AIR + 1) and (
            s.ground_min is None or s.ground_min > LATE_FROST_GROUND + 1
        )
    if kind == "heat":
        return s.air_max is not None and s.air_max < HEAT - 2
    return s.gust_max is not None and s.gust_max < STORM - 10


def worse(kind: str, new: float, old: float) -> bool:
    """Worth a second push: clearly colder / hotter / stronger than what was announced."""
    if kind in FROST_KINDS:
        return new <= old - 1.0
    if kind == "heat":
        return new >= old + 1.0
    return new >= old + 10.0


def due(e: Event, today: date) -> date:
    """Before the event, never in the past and never after this month (Heute lists the
    month): frost on the evening before its night, heat/storm the day before a morning
    event, otherwise on the day."""
    if e.kind in FROST_KINDS:
        d = e.day - timedelta(days=1)
    else:
        d = e.day if e.first.astimezone(TZ).hour >= 12 else e.day - timedelta(days=1)
    month_end = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return max(min(d, month_end), today)


def _names(plants: list[PlantInfo]) -> str:
    return ", ".join(p.title for p in plants)


def actions(kind: str, plants: list[PlantInfo]) -> list[Action]:
    kuebel = [p for p in plants if p.in_container]
    house = [p for p in plants if not p.in_container and p.standort_type == "gewaechshaus"]
    tender = [p for p in plants if not p.in_container and p.standort_type != "gewaechshaus"
              and p.growth in ("einjaehrig", "gemuese")]  # fmt: skip
    out: list[Action] = []

    def add(key: str, title: str, text: str, group: list[PlantInfo]) -> None:
        out.append(Action(key, title, text + (f"\nBetrifft: {_names(group)}." if group else ""), [p.id for p in group]))

    if kind in FROST_KINDS:
        if kuebel:
            add("kuebel", "Kübelpflanzen frostfrei stellen",
                "In Garage, Keller oder Haus stellen; wo das nicht geht: Topf mit Vlies und Jute einpacken, "
                "auf Holz oder Styropor stellen.", kuebel)  # fmt: skip
        if house:
            add("gewaechshaus", "Gewächshaus frostfrei halten",
                "Türen und Fenster schließen, Pflanzen mit Vlies abdecken, bei Bedarf Frostwächter einschalten.",
                house)  # fmt: skip
        if tender:
            add("empfindlich", "Empfindliche Pflanzen schützen",
                "Mit Vlies abdecken oder reife Früchte vorher ernten.", tender)  # fmt: skip
        if kind == "late_frost":
            bloom = [p for p in plants if p.latin in FRUIT_SPECIES and not p.in_container]
            if bloom:
                add("bluete", "Obstblüte vor Spätfrost schützen",
                    "Kleine Bäume und Sträucher abends mit Vlies abdecken (nicht auf die Blüten drücken), "
                    "morgens wieder abnehmen.", bloom)  # fmt: skip
        if kind == "strong_frost":
            add("winterschutz", "Winterschutz prüfen",
                "Rosen anhäufeln, empfindliche Gehölze mit Vlies oder Reisig schützen.", [])  # fmt: skip
    elif kind == "heat":
        if kuebel:
            add("kuebel", "Kübelpflanzen in den Schatten stellen",
                "Über Mittag in den Schatten rücken; dunkle Töpfe abdecken.", kuebel)  # fmt: skip
        if house:
            add("gewaechshaus", "Gewächshaus lüften und schattieren",
                "Fenster und Türen öffnen, Schattiernetz anbringen.", house)  # fmt: skip
    elif kind == "storm":
        if kuebel:
            add("kuebel", "Kübel sichern", "Hohe Kübel windgeschützt stellen oder hinlegen.", kuebel)
        add("sichern", "Garten sturmfest machen",
            "Vlies, Netze, Rankhilfen und lose Teile sichern; junge Bäume am Pfahl prüfen.", [])  # fmt: skip
    return out


def fmt(kind: str, value: float) -> str:
    if kind == "storm":
        return f"Böen bis {value:.0f} km/h"
    return f"{value:.1f} °C".replace(".", ",").replace("-", MINUS)
