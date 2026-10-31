"""Phenological season (M7, F-WX-2/6). Pure: DWD report parsing, the region's median
entry date per indicator phase (this year) and its long-term normal (1991-2020), the
season state with its delay against the normal, and growing degree days. The worker
downloads, the api reads Postgres.

Sources and precedence per phase and year: own observation ("garten") > DWD reports of
the region ("dwd") > estimate from the normal shifted by the current delay ("mittel")."""

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any

BASE = "https://opendata.dwd.de/climate_environment/CDC"
STATIONS_IMMEDIATE = f"{BASE}/help/PH_Beschreibung_Phaenologie_Stationen_Sofortmelder.txt"
STATIONS_ANNUAL = f"{BASE}/help/PH_Beschreibung_Phaenologie_Stationen_Jahresmelder.txt"
IMMEDIATE = f"{BASE}/observations_germany/phenology/immediate_reporters"
ANNUAL_HIST = f"{BASE}/observations_germany/phenology/annual_reporters"
NORMAL_YEARS = range(1991, 2021)
RADIUS_KM, WIDE_KM, MIN_STATIONS = 50.0, 100.0, 3
GDD_BASE = 5.0


@dataclass(frozen=True)
class Phase:
    key: str
    name: str  # the season it starts
    indicator: str  # what to look for in the garden ("Forsythie blüht")
    codes: tuple[tuple[int, int], ...]  # (Objekt_id, Phase_id) in DWD files
    immediate: str  # Sofortmelder file (current year)
    annual: str  # Jahresmelder historical file prefix (normals)


def _wild(name: str) -> tuple[str, str]:
    return (f"wild/recent/PH_Sofortmelder_Wildwachsende_Pflanze_{name}_akt.txt",
            f"wild/historical/PH_Jahresmelder_Wildwachsende_Pflanze_{name}_")  # fmt: skip


APFEL = "fruit/recent/PH_Sofortmelder_Obst_Apfel_akt.txt"
PHASES = (
    Phase("vorfruehling", "Vorfrühling", "Hasel blüht", ((113, 5),), *_wild("Hasel")),
    Phase("erstfruehling", "Erstfrühling", "Forsythie blüht", ((109, 5),), *_wild("Forsythie")),
    Phase("vollfruehling", "Vollfrühling", "Apfel blüht", ((310, 5),), APFEL,
          "fruit/historical/PH_Jahresmelder_Obst_Apfel_1"),
    Phase("fruehsommer", "Frühsommer", "Holunder blüht", ((129, 5),), *_wild("Schwarzer_Holunder")),
    Phase("hochsommer", "Hochsommer", "Sommer-Linde blüht", ((130, 5),), *_wild("Sommer-Linde")),
    Phase("spaetsommer", "Spätsommer", "Frühäpfel sind pflückreif", ((310, 29), (311, 29)), APFEL,
          "fruit/historical/PH_Jahresmelder_Obst_Apfel_fruehe_Reife_"),
    Phase("fruehherbst", "Frühherbst", "Holunderbeeren sind reif", ((129, 62),), *_wild("Schwarzer_Holunder")),
    Phase("vollherbst", "Vollherbst", "Eicheln fallen", ((132, 62),), *_wild("Stiel-Eiche")),
    Phase("spaetherbst", "Spätherbst", "Eichenlaub verfärbt sich", ((132, 31),), *_wild("Stiel-Eiche")),
    Phase("winter", "Winter", "Eichen werfen ihr Laub ab", ((132, 32),), *_wild("Stiel-Eiche")),
)  # fmt: skip
KEYS = [p.key for p in PHASES]
BY_CODE = {code: p.key for p in PHASES for code in p.codes}


@dataclass(frozen=True)
class Report:
    station: str
    year: int
    phase: str  # our key
    day: date


# ----- parsing --------------------------------------------------------------------------------


def parse_stations(text: str) -> dict[str, tuple[float, float]]:
    out = {}
    for row in text.splitlines()[1:]:
        p = [x.strip() for x in row.split(";")]
        try:
            out[str(int(p[0]))] = (float(p[2]), float(p[3]))
        except (ValueError, IndexError):
            continue
    return out


def parse_reports(lines: str | Iterable[str]) -> list[Report]:
    """Rows of a DWD phenology file (only the phases we use)."""
    out = []
    for row in lines.splitlines() if isinstance(lines, str) else lines:
        p = row.split(";")
        if len(p) < 6:
            continue
        try:
            key = BY_CODE.get((int(p[3]), int(p[4])))
            if key is None:
                continue
            raw = p[5].strip()
            out.append(Report(str(int(p[0])), int(p[1]), key, date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))))
        except ValueError:
            continue
    return out


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return 6371 * math.hypot(x, math.radians(b[0] - a[0]))


def nearby(stations: dict[str, tuple[float, float]], lat: float, lon: float, km: float) -> set[str]:
    return {sid for sid, pos in stations.items() if _km((lat, lon), pos) <= km}


def region(stations: dict[str, tuple[float, float]], lat: float, lon: float) -> set[str]:
    near = nearby(stations, lat, lon, RADIUS_KM)
    return near if len(near) >= MIN_STATIONS else nearby(stations, lat, lon, WIDE_KM)


def current(reports: list[Report], stations: set[str], year: int) -> dict[str, tuple[date, int]]:
    """Median entry date and number of reports per phase this year."""
    days: dict[str, list[date]] = defaultdict(list)
    for r in reports:
        if r.year == year and r.station in stations and r.day.year == year:
            days[r.phase].append(r.day)
    out = {}
    for key, ds in days.items():
        ordinals = sorted(d.toordinal() for d in ds)
        out[key] = (date.fromordinal(round(median(ordinals))), len(ds))
    return out


def normals(reports: Iterable[Report], stations: set[str]) -> dict[str, tuple[int, int]]:
    """Median day of year 1991-2020 per phase and the number of (station, year) values."""
    doys: dict[str, list[int]] = defaultdict(list)
    for r in reports:
        if r.year in NORMAL_YEARS and r.station in stations and r.day.year == r.year:
            doys[r.phase].append(r.day.timetuple().tm_yday)
    return {k: (round(median(v)), len(v)) for k, v in doys.items()}


# ----- season ----------------------------------------------------------------------------------


def _from_doy(year: int, doy: int) -> date:
    return date(year, 1, 1) + timedelta(days=doy - 1)


MIN_DWD_REPORTS = 2  # one early station alone does not start a season
MAX_OFF_DAYS = 60  # an own observation this far from the phase's normal is a typo, not a season


def started_events(events: dict[str, dict[str, Any]], today: date) -> list[tuple[str, dict[str, Any]]]:
    """Phases that have begun: own observations always, the region with enough reports."""
    return [
        (k, events[k])
        for k in KEYS
        if k in events
        and events[k]["day"] <= today
        and (events[k]["source"] == "garten" or events[k]["reports"] >= MIN_DWD_REPORTS)
    ]


def season(
    today: date,
    events: dict[str, dict[str, Any]],
    norm: dict[str, tuple[int, int]],
    last_winter: date | None,
) -> dict[str, Any]:
    """`events`: this year's best entry per phase {key: {day, source, reports}}.
    The current season is the begun phase with the latest date (DWD reports for neighbouring
    phases often come in a different order); the delay is the median over all begun phases
    with a normal, so a single odd date does not shift every expectation."""
    year = today.year
    started = started_events(events, today)
    offsets = [(e["day"] - _from_doy(year, norm[k][0])).days for k, e in started if k in norm]
    delay = round(median(offsets)) if offsets else 0
    phases = []
    for p in PHASES:
        got = events.get(p.key)
        normal = _from_doy(year, norm[p.key][0]) if p.key in norm else None
        counted = got is not None and (got["source"] == "garten" or got["reports"] >= MIN_DWD_REPORTS)
        expected = normal + timedelta(days=delay) if normal and not counted else None
        phases.append({
            "key": p.key, "name": p.name, "indicator": p.indicator,
            "date": got["day"].isoformat() if got else None, "source": got["source"] if got else None,
            "reports": got["reports"] if got else 0,
            "normal": normal.isoformat() if normal else None, "expected": expected.isoformat() if expected else None,
        })  # fmt: skip
    cur: dict[str, Any] | None
    if started:
        k, e = max(started, key=lambda ke: (ke[1]["day"], KEYS.index(ke[0])))
        cur = {"key": k, "since": e["day"], "source": e["source"], "reports": e["reports"]}
    elif last_winter is not None:
        cur = {"key": "winter", "since": last_winter, "source": "dwd", "reports": 0}
    elif norm:  # no reports yet: the normal calendar
        before = [p.key for p in PHASES if p.key in norm and _from_doy(year, norm[p.key][0]) <= today]
        key = before[-1] if before else "winter"
        since = _from_doy(year if before else year - 1, norm[key][0]) if key in norm else None
        cur = {"key": key, "since": since, "source": "mittel", "reports": 0} if since else None
    else:  # nothing known yet (first days after setup): better no season than a wrong one
        cur = None
    current = None
    if cur is not None:
        name = next(p.name for p in PHASES if p.key == cur["key"])
        normal_since = _from_doy(cur["since"].year, norm[cur["key"]][0]) if cur["key"] in norm else None
        cur_delay = (cur["since"] - normal_since).days if normal_since and cur["source"] != "mittel" else None
        current = {**cur, "name": name, "since": cur["since"].isoformat(), "delay_days": cur_delay}
    return {"current": current, "phases": phases, "next": _next(current, phases, year)}


def _next(current: dict[str, Any] | None, phases: list[dict[str, Any]], year: int) -> dict[str, Any] | None:
    """The next phase without a date this year, wrapping from winter to the hazel."""
    start = KEYS.index(current["key"]) + 1 if current else 0
    if current and current["key"] == "winter" and current["since"][:4] != str(year):
        start = 0  # winter that began last year: the year's first phase is next
    for p in phases[start:]:
        if not p["date"]:
            return p
    return None


def implausible(phase: str, day: date, norm: dict[str, tuple[int, int]]) -> bool:
    """An own observation far from the phase's normal (more than MAX_OFF_DAYS)."""
    if phase not in norm:
        return False
    normal = _from_doy(day.year, norm[phase][0])
    return abs((day - normal).days) > MAX_OFF_DAYS and not (phase == "winter" and day.month <= 2)


# ----- growing degree days -------------------------------------------------------------------------

MIN_GDD = 20.0  # below this (January, a cold spring) a comparison says nothing


def gdd_sum(means: Iterable[float]) -> float:
    return round(sum(max(0.0, t - GDD_BASE) for t in means), 1)


def mmdd(d: date) -> str:
    return "02-28" if (d.month, d.day) == (2, 29) else d.strftime("%m-%d")


def normal_curve(daily: dict[str, float]) -> dict[str, float]:
    """Average cumulative growing degree days per calendar day ("MM-DD"), over the years in
    `daily` ({"YYYY-MM-DD": mean °C}). Keyed by date, not position: a missing day or a
    29 February (added to the 28th) cannot shift the rest of the year."""
    per_year: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for d, t in daily.items():
        if t is not None:
            per_year[d[:4]][mmdd(date.fromisoformat(d))] += max(0.0, t - GDD_BASE)
    days = sorted({k for y in per_year.values() for k in y})
    if not per_year or not days:
        return {}
    curve, total = {}, 0.0
    for k in days:
        total += sum(y.get(k, 0.0) for y in per_year.values()) / len(per_year)
        curve[k] = round(total, 1)
    return curve


def days_ahead(current_sum: float, today: date, curve: dict[str, float]) -> int | None:
    """Positive: the season is that many days ahead of the average year (None in winter
    or without a curve)."""
    if current_sum < MIN_GDD or not curve:
        return None
    reached = next((k for k in sorted(curve) if curve[k] >= current_sum), None)
    if reached is None:
        return None
    ref = 2001  # any non-leap year: both dates on the same 365-day axis
    return (date.fromisoformat(f"{ref}-{reached}") - date.fromisoformat(f"{ref}-{mmdd(today)}")).days
