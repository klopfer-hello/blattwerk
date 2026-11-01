"""Downloads for the phenological season (M7a), run by the worker (the one with internet).

Daily: DWD Sofortmelder of the indicator plants (small files, this and last year) ->
region medians in pheno_events; Open-Meteo archive -> growing degree days this year.
Once per region (back-off after a failure): DWD Jahresmelder historical files, streamed line by line and
never stored -> pheno_normals; the GDD climatology 1991-2020. Only fixed DWD and
Open-Meteo URLs; coordinates rounded to 2 decimals (about 1 km); no station ids logged."""

import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from blattwerk import pheno
from blattwerk.schema import kv, pheno_events, pheno_normals

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
BACKOFF = timedelta(days=3)
NORMALS_VERSION = 2  # bump when the phase/file mapping changes: normals are recomputed once
log = logging.getLogger("blattwerk.pheno")
MAX_SMALL = 10_000_000


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=120, follow_redirects=False)


async def _text(c: httpx.AsyncClient, url: str) -> str:
    """A small file, read with a cap (streamed: a huge answer is cut off, not held)."""
    parts, size = [], 0
    async with c.stream("GET", url) as r:
        r.raise_for_status()
        async for chunk in r.aiter_bytes():
            size += len(chunk)
            if size > MAX_SMALL:
                raise ValueError("file too large")
            parts.append(chunk)
    return b"".join(parts).decode("latin-1")


async def _lines(c: httpx.AsyncClient, url: str) -> AsyncIterator[str]:
    async with c.stream("GET", url) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            yield line


async def _kv(engine: AsyncEngine, key: str, value: dict[str, Any]) -> None:
    async with engine.begin() as conn:
        stmt = pg_insert(kv).values(key=key, value=value)
        await conn.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value}))


async def update_current(engine: AsyncEngine, lat: float, lon: float, today: date) -> int:
    """This and last year's region medians from the Sofortmelder; a failing file costs only
    its phases. Returns the number of phases found this year."""
    async with _client() as c:
        stations = pheno.region(pheno.parse_stations(await _text(c, pheno.STATIONS_IMMEDIATE)), lat, lon)
        reports: list[pheno.Report] = []
        for path in sorted({p.immediate for p in pheno.PHASES}):
            try:
                reports += pheno.parse_reports(await _text(c, f"{pheno.IMMEDIATE}/{path}"))
            except (httpx.HTTPError, ValueError) as e:
                log.warning("phenology file failed: %s", type(e).__name__)
    found = 0
    stamp = datetime.now(UTC)
    async with engine.begin() as conn:
        for year in (today.year - 1, today.year):
            for phase, (day, n) in pheno.current(reports, stations, year).items():
                stmt = pg_insert(pheno_events).values(year=year, phase=phase, source="dwd", day=day, reports=n,
                                                      updated_at=stamp)  # fmt: skip
                await conn.execute(stmt.on_conflict_do_update(
                    index_elements=["year", "phase", "source"],
                    set_={"day": stmt.excluded.day, "reports": stmt.excluded.reports, "updated_at": stamp},
                ))  # fmt: skip
                found += year == today.year
    return found


def _fingerprint(lat: float, lon: float) -> str:
    return f"v{NORMALS_VERSION}:{lat:.1f},{lon:.1f}"  # about 10 km: the region does not change for less


async def _job(engine: AsyncEngine) -> dict[str, Any]:
    async with engine.connect() as conn:
        return dict((await conn.execute(select(kv.c.value).where(kv.c.key == "pheno_normals_job"))).scalar() or {})


async def normals_due(engine: AsyncEngine, lat: float, lon: float, now: datetime) -> bool:
    """Normals 1991-2020 do not change: computed once per region; after a failed attempt
    again only after BACKOFF (the files are 25-100 MB each)."""
    job = await _job(engine)
    if job.get("region") != _fingerprint(lat, lon):
        return True  # new region or a new phase/file mapping: at once
    if job.get("done"):
        return False
    last = job.get("attempt_at")  # the same region failed before: wait
    return last is None or now - datetime.fromisoformat(last) > BACKOFF


async def _latest_hist(c: httpx.AsyncClient, prefix: str) -> str:
    """The newest historical file for a prefix (the name carries the year range, e.g. _1930_2024_hist)."""
    folder, name = prefix.rsplit("/", 1)
    listing = await _text(c, f"{pheno.ANNUAL_HIST}/{folder}/")
    found = sorted(set(re.findall(re.escape(name) + r"[0-9_]*_hist\.txt", listing)), key=lambda n: n[-14:-9])
    if not found:
        raise ValueError("historical file not found")
    return f"{pheno.ANNUAL_HIST}/{folder}/{found[-1]}"


async def update_normals(engine: AsyncEngine, lat: float, lon: float) -> int:
    """Long-term medians 1991-2020; streams each historical file, keeps only the region's rows
    and only the phases that file stands for, writes each file's result right away."""
    region = _fingerprint(lat, lon)
    await _kv(
        engine, "pheno_normals_job", {"region": region, "attempt_at": datetime.now(UTC).isoformat(), "done": False}
    )
    written, failed = 0, 0
    async with _client() as c:
        stations = pheno.region(pheno.parse_stations(await _text(c, pheno.STATIONS_ANNUAL)), lat, lon)
        for prefix in sorted({p.annual for p in pheno.PHASES}):
            keys = {p.key for p in pheno.PHASES if p.annual == prefix}
            try:
                url = await _latest_hist(c, prefix)
                reports = [r async for r in _region_reports(_lines(c, url), stations) if r.phase in keys]
            except (httpx.HTTPError, ValueError) as e:  # this plant later (back-off), the others now
                failed += 1
                log.warning("phenology normals file failed: %s", type(e).__name__)
                continue
            stamp = datetime.now(UTC)
            async with engine.begin() as conn:
                for phase, (doy, n) in pheno.normals(reports, stations).items():
                    stmt = pg_insert(pheno_normals).values(phase=phase, doy=doy, stations=n, computed_at=stamp)
                    await conn.execute(stmt.on_conflict_do_update(
                        index_elements=["phase"], set_={"doy": doy, "stations": n, "computed_at": stamp},
                    ))  # fmt: skip
                    written += 1
    done = {"region": region, "attempt_at": datetime.now(UTC).isoformat(), "done": failed == 0}
    await _kv(engine, "pheno_normals_job", done)
    return written


async def _region_reports(lines: AsyncIterator[str], stations: set[str]) -> AsyncIterator[pheno.Report]:
    async for line in lines:
        head = line.split(";", 2)
        if len(head) > 2 and head[0].strip().isdigit() and str(int(head[0])) in stations:
            for r in pheno.parse_reports([line]):
                if r.year in pheno.NORMAL_YEARS:
                    yield r


async def _daily_means(lat: float, lon: float, start: str, end: str) -> dict[str, float]:
    params = {"latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}", "start_date": start, "end_date": end,
              "daily": "temperature_2m_mean", "timezone": "Europe/Berlin"}  # fmt: skip
    async with _client() as c:
        r = await c.get(ARCHIVE, params=params)
        r.raise_for_status()
    d = r.json()["daily"]
    return {t: v for t, v in zip(d["time"], d["temperature_2m_mean"], strict=True) if v is not None}


async def update_gdd(engine: AsyncEngine, lat: float, lon: float, today: date) -> float:
    async with engine.connect() as conn:
        old = (await conn.execute(select(kv.c.value).where(kv.c.key == "gdd"))).scalar() or {}
    curve = old.get("curve") if isinstance(old.get("curve"), dict) else None
    if not curve:  # climatology once: 30 years of daily means, about 11 000 values
        curve = pheno.normal_curve(await _daily_means(lat, lon, "1991-01-01", "2020-12-31"))
        if not curve:
            raise ValueError("no climatology")
    means = await _daily_means(lat, lon, f"{today.year}-01-01", today.isoformat())
    total = pheno.gdd_sum(means.values())
    as_of = max(means) if means else today.isoformat()
    await _kv(engine, "gdd", {"year": today.year, "sum": total, "as_of": as_of, "curve": curve})
    return total
