"""Phenology (M7a): DWD report parsing (invented stations far from the garden), region
median, long-term normals, the season state and growing degree days; the season API
with own observations."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from blattwerk import pheno
from tests.conftest import BASE

H = {"Origin": BASE}

STATIONS = """Stations_id;Stationsname                               ;geograph.Breite;geograph.Laenge;Stationshoehe;eor;
00001                     ;Nordhausen-Test     ;    54.5000    ;   9.5000     ;   20       ;eor;
00002                     ;Nebenan-Test        ;    54.6000    ;   9.6000     ;   30       ;eor;
00003                     ;Weitweg-Test        ;    50.0000    ;   7.0000     ;  200       ;eor;
"""


def report(station: int, year: int, obj: int, phase: int, day: str) -> str:
    doy = (date.fromisoformat(day) - date(int(day[:4]), 1, 1)).days + 1
    return f"{station:>12};{year:>14};{1:>17};{obj:>17};{phase:>15};{day.replace('-', ''):>16};{1:>17};{doy:>7};eor;"


HEAD = "Stations_id; Referenzjahr; Qualitaetsniveau; Objekt_id; Phase_id; Eintrittsdatum;Eintrittsdatum_QB; Jultag;eor;"


def test_station_list_is_parsed() -> None:
    st = pheno.parse_stations(STATIONS)
    assert st["1"] == (54.5, 9.5) and len(st) == 3


def test_region_uses_50_km_and_widens_when_too_few() -> None:
    st = pheno.parse_stations(STATIONS)
    assert pheno.nearby(st, 54.55, 9.55, 50) == {"1", "2"}
    assert pheno.nearby(st, 50.1, 7.1, 50) == {"3"}


def test_current_year_median_per_phase() -> None:
    lines = [HEAD, report(1, 2026, 109, 5, "2026-03-20"), report(2, 2026, 109, 5, "2026-03-24"),
             report(3, 2026, 109, 5, "2026-02-01"), report(1, 2025, 109, 5, "2025-03-01")]  # fmt: skip
    got = pheno.current(pheno.parse_reports("\n".join(lines)), {"1", "2"}, 2026)
    assert got["erstfruehling"] == (date(2026, 3, 22), 2)


def test_spaetsommer_uses_early_apple_in_both_files() -> None:
    lines = [HEAD, report(1, 2026, 310, 29, "2026-08-10"), report(1, 2000, 311, 29, "2000-08-14")]
    rows = pheno.parse_reports("\n".join(lines))
    assert pheno.current(rows, {"1"}, 2026)["spaetsommer"][0] == date(2026, 8, 10)
    assert pheno.normals(rows, {"1"})["spaetsommer"] == (227, 1)


def test_apple_blossom_normal_comes_from_the_early_variety() -> None:
    lines = [HEAD, report(1, 2000, 311, 5, "2000-04-25"), report(1, 1985, 310, 5, "1985-05-05")]
    assert pheno.normals(pheno.parse_reports("\n".join(lines)), {"1"})["vollfruehling"] == (116, 1)


def test_normals_are_the_median_day_1991_to_2020() -> None:
    lines = [HEAD] + [report(1, y, 113, 5, f"{y}-02-{10 + (y % 5)}") for y in range(1985, 2026)]
    doy, n = pheno.normals(pheno.parse_reports("\n".join(lines)), {"1"})["vorfruehling"]
    assert n == 30 and doy == 43  # 12 February


# ----- season state ---------------------------------------------------------------------------

NORMALS = {"vorfruehling": (50, 30), "erstfruehling": (80, 30), "vollfruehling": (115, 30),
           "fruehsommer": (150, 30), "hochsommer": (180, 30), "spaetsommer": (215, 30), "fruehherbst": (240, 30),
           "vollherbst": (260, 30), "spaetherbst": (290, 30), "winter": (310, 30)}  # fmt: skip


def ev(**kw: tuple[str, str]) -> dict[str, dict[str, object]]:
    return {k: {"day": date.fromisoformat(d), "source": s, "reports": 3} for k, (d, s) in kw.items()}


def test_season_is_the_latest_started_phase_with_its_delay() -> None:
    events = ev(vorfruehling=("2026-02-25", "dwd"), erstfruehling=("2026-03-25", "dwd"))
    s = pheno.season(date(2026, 4, 2), events, NORMALS, last_winter=None)
    assert s["current"]["key"] == "erstfruehling" and s["current"]["since"] == "2026-03-25"
    assert s["current"]["delay_days"] == 4  # 25.3. is day 84, normal 80
    nxt = next(p for p in s["phases"] if p["key"] == "vollfruehling")
    assert nxt["date"] is None and nxt["expected"] == "2026-04-30"  # normal 115 + median delay (6, 4) = 5
    assert s["next"]["key"] == "vollfruehling"


def test_own_observation_wins() -> None:
    events = ev(vorfruehling=("2026-02-25", "dwd"))
    events["erstfruehling"] = {"day": date(2026, 3, 10), "source": "garten", "reports": 1}
    s = pheno.season(date(2026, 3, 12), events, NORMALS, last_winter=None)
    assert s["current"]["key"] == "erstfruehling" and s["current"]["source"] == "garten"


def test_before_the_hazel_it_is_still_winter() -> None:
    s = pheno.season(date(2026, 1, 20), {}, NORMALS, last_winter=date(2025, 11, 8))
    assert s["current"]["key"] == "winter" and s["current"]["since"] == "2025-11-08"


def test_without_any_data_the_season_is_estimated_from_the_normals() -> None:
    s = pheno.season(date(2026, 6, 10), {}, NORMALS, last_winter=None)
    assert s["current"]["key"] == "fruehsommer" and s["current"]["source"] == "mittel"


# ----- growing degree days ----------------------------------------------------------------------


def test_gdd_and_how_many_days_ahead() -> None:
    daily = {f"{y}-{m:02d}-{d:02d}": 10.0 for y in (2001, 2002) for m in (1, 2) for d in range(1, 29)}
    curve = pheno.normal_curve(daily)
    assert curve["01-01"] == 5.0 and curve["01-10"] == 50.0  # 10 days at 10 °C: 5 °C above the base each
    assert pheno.gdd_sum([10.0] * 12) == 60.0
    assert pheno.days_ahead(60.0, date(2026, 1, 10), curve) == 2  # the normal reaches 60 on 12 January


def test_gdd_curve_is_keyed_by_date_in_leap_years() -> None:
    daily = {"2004-02-28": 10.0, "2004-02-29": 10.0, "2004-03-01": 10.0, "2005-02-28": 10.0, "2005-03-01": 10.0}
    curve = pheno.normal_curve(daily)
    assert list(curve) == ["02-28", "03-01"] and curve["02-28"] == 7.5  # 29 Feb added to the 28th: (10 + 5) / 2


def test_gdd_says_nothing_in_winter() -> None:
    assert pheno.days_ahead(3.0, date(2026, 1, 20), {"01-01": 0.0}) is None


def test_nothing_known_means_no_season_rather_than_winter() -> None:
    assert pheno.season(date(2026, 7, 10), {}, {}, last_winter=None)["current"] is None


def test_in_winter_the_hazel_is_next() -> None:
    s = pheno.season(date(2026, 1, 20), {}, NORMALS, last_winter=date(2025, 11, 8))
    assert s["next"]["key"] == "vorfruehling" and s["next"]["expected"] == "2026-02-19"


def test_one_early_report_does_not_start_a_season() -> None:
    events = {"vollfruehling": {"day": date(2026, 3, 1), "source": "dwd", "reports": 1}}
    events |= ev(erstfruehling=("2026-03-20", "dwd"))
    assert pheno.season(date(2026, 3, 25), events, NORMALS, None)["current"]["key"] == "erstfruehling"


def test_phases_reported_out_of_order_take_the_latest_date() -> None:
    events = ev(spaetsommer=("2026-08-30", "dwd"), fruehherbst=("2026-08-20", "dwd"))
    assert pheno.season(date(2026, 9, 1), events, NORMALS, None)["current"]["key"] == "spaetsommer"


def test_implausible_observation() -> None:
    assert pheno.implausible("vorfruehling", date(2026, 7, 1), NORMALS)
    assert not pheno.implausible("vorfruehling", date(2026, 3, 1), NORMALS)


# ----- API -----------------------------------------------------------------------------------------


def test_season_api_with_observation(client: TestClient, db: Engine) -> None:
    today = date.today()
    with db.begin() as c:  # every phase "usually" today: an observation today is plausible for each
        for k in NORMALS:
            c.execute(text("INSERT INTO pheno_normals (phase, doy, stations, computed_at) VALUES (:k, :d, 30, now())"),
                      {"k": k, "d": today.timetuple().tm_yday})  # fmt: skip
    s = client.get("/api/season").json()
    assert s["current"]["source"] == "mittel" and len(s["phases"]) == 10
    r = client.post("/api/season/observations", json={"phase": "vorfruehling", "day": today.isoformat()}, headers=H)
    assert r.status_code == 201, r.text
    s = client.get("/api/season").json()
    assert next(p for p in s["phases"] if p["key"] == "vorfruehling")["source"] == "garten"
    assert client.delete("/api/season/observations/vorfruehling", headers=H).status_code == 204


@pytest.mark.parametrize(
    "body",
    [
        {"phase": "sommer", "day": "2026-01-01"},
        {"phase": "winter", "day": "2099-01-01"},
        {"phase": "vorfruehling", "day": f"{date.today().year - 1}-12-28"},  # last year: only winter
    ],
)
def test_bad_observations(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/api/season/observations", json=body, headers=H).status_code == 422


def test_implausible_observation_is_refused(client: TestClient, db: Engine) -> None:
    far = (date.today().timetuple().tm_yday + 120) % 365 + 1
    with db.begin() as c:
        sql = "INSERT INTO pheno_normals (phase, doy, stations, computed_at) VALUES ('vollherbst', :d, 30, now())"
        c.execute(text(sql), {"d": far})
    r = client.post(
        "/api/season/observations", json={"phase": "vollherbst", "day": date.today().isoformat()}, headers=H
    )
    assert r.status_code == 422


def test_normals_job_runs_at_once_for_a_new_region_and_backs_off_after_a_failure(db: Engine) -> None:
    import asyncio
    import json
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import create_async_engine

    from blattwerk import pheno_fetch
    from tests.conftest import DATABASE_URL

    def due(job: dict[str, object]) -> bool:
        with db.begin() as c:
            c.execute(text("DELETE FROM kv WHERE key = 'pheno_normals_job'"))
            c.execute(text("INSERT INTO kv (key, value) VALUES ('pheno_normals_job', CAST(:v AS jsonb))"),
                      {"v": json.dumps(job)})  # fmt: skip

        async def go() -> bool:
            engine = create_async_engine(DATABASE_URL)
            try:
                return await pheno_fetch.normals_due(engine, 54.0, 9.0, datetime.now(UTC))
            finally:
                await engine.dispose()

        return asyncio.run(go())

    now = datetime.now(UTC).isoformat()
    region = pheno_fetch._fingerprint(54.0, 9.0)
    assert due({"region": "v1:54.0,9.0", "attempt_at": now, "done": True})  # old mapping: again, at once
    assert not due({"region": region, "attempt_at": now, "done": True})
    assert not due({"region": region, "attempt_at": now, "done": False})  # failed just now: wait
    old = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    assert due({"region": region, "attempt_at": old, "done": False})


def test_hazel_in_december_counts_for_the_next_reference_year() -> None:
    lines = [HEAD, report(1, 2026, 113, 5, "2025-12-28"), report(2, 2026, 113, 5, "2026-01-05"),
             report(1, 2000, 113, 5, "1999-12-22"), report(1, 2001, 113, 5, "2001-01-01")]  # fmt: skip
    rows = pheno.parse_reports("\n".join(lines))
    assert pheno.current(rows, {"1", "2"}, 2026)["vorfruehling"] == (date(2026, 1, 1), 2)  # median of 28.12. and 5.1.
    doy, n = pheno.normals(rows, {"1"})["vorfruehling"]
    assert n == 2 and doy in (-4, -5)  # between 22.12. (-9) and 1.1. (1)


def test_december_hazel_has_a_sane_delay_and_can_be_observed(client: TestClient, db: Engine) -> None:
    with db.begin() as c:
        sql = "INSERT INTO pheno_normals (phase, doy, stations, computed_at) VALUES ('vorfruehling', 40, 30, now())"
        c.execute(text(sql))
    events = {"vorfruehling": {"day": date(2026, 12, 20), "source": "dwd", "reports": 3}}
    s = pheno.season(date(2027, 1, 5), events, {"vorfruehling": (40, 30)}, None)  # 2027's hazel, seen in December
    assert s["current"]["delay_days"] == -51  # 20.12.2026 vs 9.2.2027: 51 days earlier
    assert pheno.reference_year("vorfruehling", date(2026, 12, 20)) == 2027
    assert not pheno.implausible("vorfruehling", date(2026, 12, 20), {"vorfruehling": (-10, 30)})


def test_other_phases_do_not_cross_the_year() -> None:
    lines = [HEAD, report(1, 2026, 109, 5, "2025-12-30")]  # a Forsythia "in 2025" for 2026: a stray row
    assert pheno.current(pheno.parse_reports("\n".join(lines)), {"1"}, 2026) == {}
