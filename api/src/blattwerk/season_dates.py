"""The season for the rest of the app (M7): the state shown in the UI (without growing
degree days, which the season route adds) and the phase start dates the to-do engine
and the alerts use. Not a route module, so routes.todos and routes.season can both
import it.

Phase starts: this and last year the observed date, or a region date with enough
reports; otherwise the expected date (normal + current delay); other years the normal.
Nothing known -> no date -> the task's month window."""

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from blattwerk import pheno
from blattwerk.schema import pheno_events, pheno_normals

log = logging.getLogger(__name__)


async def best_events(c: AsyncConnection, year: int) -> dict[str, dict[str, Any]]:
    """Per phase the entry that counts: own observation before the region."""
    rows = await c.execute(select(pheno_events).where(pheno_events.c.year == year))
    out: dict[str, dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: r.source != "garten"):  # garten first
        out.setdefault(r.phase, {"day": r.day, "source": r.source, "reports": r.reports})
    return out


async def season_core(c: AsyncConnection, today: date) -> dict[str, Any]:
    norm = {r.phase: (r.doy, r.stations) for r in await c.execute(select(pheno_normals))}
    events = await best_events(c, today.year)
    last = (await best_events(c, today.year - 1)).get("winter")
    state = pheno.season(today, events, norm, last["day"] if last else None)
    state["region_ready"] = bool(norm)
    return state


def _same_doy(normal: date, ref: int, year: int) -> date:
    """The normal is days from 1 January of its reference year `ref` (may be <= 0 for a December
    hazel): the same offset from 1 January of `year`."""
    return date(year, 1, 1) + (normal - date(ref, 1, 1))


async def phase_starts(c: AsyncConnection, today: date) -> dict[tuple[int, str], date]:
    state = await season_core(c, today)
    out: dict[tuple[int, str], date] = {}
    for p in state["phases"]:
        counted = p["date"] and (p["source"] == "garten" or p["reports"] >= pheno.MIN_DWD_REPORTS)
        best = p["date"] if counted else p["expected"]
        if best:
            out[(today.year, p["key"])] = date.fromisoformat(best)
        if p["normal"]:
            normal = date.fromisoformat(p["normal"])
            for y in (today.year - 1, today.year + 1):
                out[(y, p["key"])] = _same_doy(normal, today.year, y)
    for key, e in (await best_events(c, today.year - 1)).items():  # last year: what really happened
        if e["source"] == "garten" or e["reports"] >= pheno.MIN_DWD_REPORTS:
            out[(today.year - 1, key)] = e["day"]
    return out


async def safe_phase_starts(c: AsyncConnection, today: date) -> dict[tuple[int, str], date]:
    """For Heute and the alerts: phenology trouble means month windows, never an error."""
    try:
        async with c.begin_nested():
            return await phase_starts(c, today)
    except Exception as e:
        log.warning("phase starts unavailable: %s", type(e).__name__)
        return {}


def late_frost_from(starts: dict[tuple[int, str], date], year: int) -> date | None:
    """Late frost matters from the apple blossom (Vollfrühling) on."""
    return starts.get((year, "vollfruehling"))
