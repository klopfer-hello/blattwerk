"""The DWD phenology downloads (M7, ticket 033) against a fake DWD: newest historical file
from the listing, a failing file costs only its phases, normals only from the region and
only for the phases a file stands for."""

import asyncio
from datetime import date
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from blattwerk import pheno, pheno_fetch
from tests.conftest import DATABASE_URL
from tests.test_pheno import HEAD, STATIONS, report

LISTING = """<a href="PH_Jahresmelder_Wildwachsende_Pflanze_Hasel_1930_2018_hist.txt">x</a>
<a href="PH_Jahresmelder_Wildwachsende_Pflanze_Hasel_1930_2024_hist.txt">x</a>
<a href="PH_Jahresmelder_Wildwachsende_Pflanze_Hasel_1930_2019_hist.txt">x</a>"""


def fake_dwd(files: dict[str, str]) -> httpx.MockTransport:
    def handler(r: httpx.Request) -> httpx.Response:
        for suffix, body in files.items():
            if str(r.url).endswith(suffix):
                return httpx.Response(200, content=body.encode("latin-1"))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def run_with(transport: httpx.MockTransport, coro_fn: Any, *args: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await coro_fn(engine, *args)
        finally:
            await engine.dispose()

    original = pheno_fetch._client
    pheno_fetch._client = lambda: httpx.AsyncClient(transport=transport)  # type: ignore[assignment]
    try:
        return asyncio.run(go())
    finally:
        pheno_fetch._client = original  # type: ignore[assignment]


def test_latest_historical_file_is_the_one_with_the_newest_end_year() -> None:
    async def go() -> str:
        async with httpx.AsyncClient(transport=fake_dwd({"/wild/historical/": LISTING})) as c:
            return await pheno_fetch._latest_hist(c, "wild/historical/PH_Jahresmelder_Wildwachsende_Pflanze_Hasel_")

    assert asyncio.run(go()).endswith("Hasel_1930_2024_hist.txt")


def test_a_failing_file_costs_only_its_phases(db: Engine) -> None:
    files = {
        "Stationen_Sofortmelder.txt": STATIONS,
        "Forsythie_akt.txt": "\n".join(
            [
                HEAD,
                report(1, 2026, 109, 5, "2026-03-20"),
                report(2, 2026, 109, 5, "2026-03-22"),
                report(3, 2026, 109, 5, "2026-03-01"),
            ]
        ),
    }  # everything else answers 404
    found = run_with(fake_dwd(files), pheno_fetch.update_current, 54.55, 9.55, date(2026, 4, 1))
    assert found == 1
    with db.connect() as c:
        rows = c.execute(text("SELECT phase, day, reports FROM pheno_events")).all()
    assert [(r.phase, r.day, r.reports) for r in rows] == [("erstfruehling", date(2026, 3, 21), 2)]  # station 3 is far


@pytest.mark.parametrize("phase_file", ["Hasel"])
def test_normals_only_from_the_region_and_the_file_phases(db: Engine, phase_file: str) -> None:
    hist = "\n".join([HEAD] + [report(1, y, 113, 5, f"{y}-02-15") for y in range(1991, 2021)]
                     + [report(3, y, 113, 5, f"{y}-01-01") for y in range(1991, 2021)]  # far away
                     + [report(1, 2000, 109, 5, "2000-03-30")])  # a Forsythia row in the hazel file  # fmt: skip
    files = {"Stationen_Jahresmelder.txt": STATIONS, "/wild/historical/": LISTING,
             "Hasel_1930_2024_hist.txt": hist}  # fmt: skip
    for p in pheno.PHASES:  # the other plants' files exist but are empty listings
        files.setdefault(p.annual.rsplit("/", 1)[0] + "/", LISTING)
    assert run_with(fake_dwd(files), pheno_fetch.update_normals, 54.55, 9.55) == 1  # the other plants: no file here
    with db.connect() as c:
        rows = c.execute(text("SELECT phase, doy, stations FROM pheno_normals")).all()
        job = c.execute(text("SELECT value FROM kv WHERE key = 'pheno_normals_job'")).scalar()
    assert [(r.phase, r.doy, r.stations) for r in rows] == [("vorfruehling", 46, 30)]
    assert job["done"] is False  # the missing ones are tried again after the back-off
