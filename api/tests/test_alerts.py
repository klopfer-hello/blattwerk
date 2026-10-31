"""Weather alerts (M6b, F-WX-4): detection from the forecast (pure), what to do for
which plants (pure), and the wetterwacht run against Postgres with a fake forecast:
one alert per event, urgent to-dos, one push, updates only when it gets worse,
all-clear when the forecast clears."""

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from garten_planer import alerts
from garten_planer.alerts import Hour, PlantInfo, actions, detect
from garten_planer.plan import WATERING
from garten_planer.wetterwacht import SCENARIOS, run_once, scenario_hours
from tests.conftest import BASE, DATABASE_URL
from tests.test_push import sub

TZ = ZoneInfo("Europe/Berlin")
H = {"Origin": BASE}


def hours(start: datetime, temps: list[float], gust: float = 10.0, ground: float | None = None) -> list[Hour]:
    return [Hour(start + timedelta(hours=i), t, ground if ground is not None else t, gust) for i, t in enumerate(temps)]


def at(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=TZ)


# ----- detection --------------------------------------------------------------------------


def test_early_cold_wave_in_october_is_a_frost_alert() -> None:
    now = at(2026, 10, 12)
    ev = detect(hours(now, [8, 4, 1, -1, -3.5, -2, 2] + [6] * 40), now)
    assert [(e.kind, e.value) for e in ev] == [("frost", -3.5)]
    assert ev[0].day == date(2026, 10, 13)  # the night to Tuesday


def test_a_frost_night_over_midnight_is_one_event_due_the_evening_before() -> None:
    now = at(2026, 10, 14, 18)
    ev = detect(hours(now, [3, 1, -1, -2.5, -3, -3.5, -4, -3.8, -3, -2.2, 0] + [6] * 30), now)  # 18:00 to 04:00
    assert [(e.kind, e.day, e.value) for e in ev] == [("frost", date(2026, 10, 15), -4)]
    assert alerts.due(ev[0], date(2026, 10, 14)) == date(2026, 10, 14)


def test_frost_in_january_is_expected_and_no_alert() -> None:
    now = at(2027, 1, 12)
    assert detect(hours(now, [-4] * 48), now) == []


def test_strong_frost_alerts_even_in_winter() -> None:
    now = at(2027, 1, 12)
    assert [e.kind for e in detect(hours(now, [-4] * 20 + [-11] + [-4] * 20), now)] == ["strong_frost"]


def test_late_frost_after_blossom_start_counts_from_zero_degrees_and_the_ground() -> None:
    now = at(2026, 4, 20)
    ev = detect(hours(now, [5] * 10, ground=5) + hours(now + timedelta(hours=10), [1, 0.5], ground=-1.5), now)
    assert [(e.kind, e.value) for e in ev] == [("late_frost", -1.5)]


def test_heat_and_storm() -> None:
    now = at(2026, 7, 10)
    ev = detect(hours(now, [25, 30, 33.5, 31] + [24] * 30) + hours(now + timedelta(hours=40), [20], gust=82), now)
    assert sorted((e.kind, e.value) for e in ev) == [("heat", 33.5), ("storm", 82)]


def test_only_the_next_48_hours_count() -> None:
    now = at(2026, 10, 12)
    assert detect(hours(now, [6] * 50 + [-5]), now) == []


def test_one_event_per_kind_and_day() -> None:
    now = at(2026, 10, 12, 0)
    temps = [5] * 14 + [-2.5, -4, -3] + [5] * 23 + [-2.2] + [5] * 6  # 14:00 on the 12th and 16:00 on the 13th
    ev = detect(hours(now, temps), now)
    assert [(e.day, e.value) for e in ev] == [(date(2026, 10, 13), -4), (date(2026, 10, 14), -2.2)]


# ----- actions ------------------------------------------------------------------------------

KUEBEL = PlantInfo("p1", "Zitrone", in_container=True, growth="kuebel", standort_type="kuebelplatz",
                   latin="Citrus limon")  # fmt: skip
TOMATE = PlantInfo("p2", "Tomate", in_container=False, growth="gemuese", standort_type="gewaechshaus",
                   latin="Solanum lycopersicum")  # fmt: skip
APFEL = PlantInfo("p3", "Apfel", in_container=False, growth="baum", standort_type="beet", latin="Malus domestica")
HECKE = PlantInfo("p4", "Hainbuche", in_container=False, growth="hecke", standort_type="hecke",
                  latin="Carpinus betulus")  # fmt: skip
ALL = [KUEBEL, TOMATE, APFEL, HECKE]


def keys(kind: str) -> dict[str, list[str]]:
    return {a.key: a.plant_ids for a in actions(kind, ALL)}


def test_frost_actions() -> None:
    assert keys("frost") == {"kuebel": ["p1"], "gewaechshaus": ["p2"]}


def test_late_frost_protects_the_blossom_of_fruit_trees() -> None:
    assert keys("late_frost")["bluete"] == ["p3"]


def test_heat_never_suggests_watering() -> None:
    for a in actions("heat", ALL):
        assert not WATERING.search(a.title + a.instructions)


def test_storm_has_a_garden_wide_action_too() -> None:
    assert keys("storm") == {"kuebel": ["p1"], "sichern": []}


def test_hedge_alone_gets_no_frost_action() -> None:
    assert actions("frost", [HECKE]) == []


# ----- scenarios (/weather-sim) ---------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_produces_its_expected_alerts(name: str) -> None:
    sc = SCENARIOS[name]
    now = datetime.fromisoformat(sc["now"])
    assert sorted(e.kind for e in detect(scenario_hours(sc), now)) == sorted(sc["expect"])


# ----- wetterwacht run (Postgres, fake forecast) ------------------------------------------------


def run(fc: list[Hour], now: datetime) -> dict[str, int]:
    async def go() -> dict[str, int]:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_once(engine, fc, now)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def setup_garden(client: TestClient) -> str:
    st = client.post("/api/standorte", json={"name": "Terrasse", "light": "sonnig", "type": "kuebelplatz"},
                     headers=H).json()  # fmt: skip
    body = {"species_id": "malus-domestica", "standort_id": st["id"], "in_container": True, "nickname": "Kübelapfel"}
    pid = str(client.post("/api/plants", json=body, headers=H).json()["id"])
    r = client.post("/api/push/subscriptions", json=sub("https://fcm.googleapis.com/fcm/send/abc"), headers=H)
    assert r.status_code == 201, r.text
    return pid


def count(db: Engine, sql: str) -> int:
    with db.connect() as c:
        return int(c.execute(text(sql)).scalar() or 0)


def test_run_creates_one_alert_with_urgent_todo_and_one_push(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 10)
    fc = hours(now, [8, 4, 1, -1, -3.5, -2] + [6] * 40)
    assert run(fc, now)["created"] == 1
    assert run(fc, now + timedelta(minutes=10))["created"] == 0  # same event: nothing new
    assert count(db, "SELECT count(*) FROM weather_alerts") == 1
    assert count(db, "SELECT count(*) FROM tasks WHERE source = 'alert' AND urgent") == 1
    assert count(db, "SELECT count(*) FROM todos t JOIN tasks k ON k.id = t.task_id WHERE k.source = 'alert'") == 1
    pushes = count(db, "SELECT count(*) FROM push_messages")
    assert pushes == 1


def test_worse_forecast_updates_and_pushes_again_better_does_not(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 10)
    run(hours(now, [5, -2.5] + [6] * 40), now)
    run(hours(now, [5, -2.8] + [6] * 40), now)  # 0.3 °C worse: not worth a push
    assert count(db, "SELECT count(*) FROM push_messages") == 1
    assert run(hours(now, [5, -5] + [6] * 40), now)["worse"] == 1
    assert count(db, "SELECT count(*) FROM push_messages") == 2
    assert count(db, "SELECT count(*) FROM weather_alerts WHERE value = -5") == 1


def test_cleared_forecast_cancels_and_removes_open_todos(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 10)
    night = [5] * 14  # frost at midnight: the night to the 13th, its window starts at noon
    run(hours(now, [*night, -3] + [6] * 30), now)
    run(hours(now, [*night, -1.5] + [6] * 30), now)  # just above the threshold: stays (no flapping)
    assert count(db, "SELECT count(*) FROM weather_alerts WHERE status = 'active'") == 1
    assert run(hours(now, [*night, 3] + [6] * 30), now)["cancelled"] == 1
    assert count(db, "SELECT count(*) FROM todos t JOIN tasks k ON k.id = t.task_id "
                     "WHERE k.source = 'alert' AND t.status = 'open'") == 0  # fmt: skip
    assert count(db, "SELECT count(*) FROM push_messages") == 2  # the warning and the all-clear


def test_no_push_when_weather_push_is_off(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    s = client.get("/api/settings").json()
    s["notifications"]["weather_push"] = False
    client.put("/api/settings", json=s, headers=H)
    now = at(2026, 10, 12, 10)
    run(hours(now, [5, -3] + [6] * 40), now)
    assert count(db, "SELECT count(*) FROM push_messages") == 0
    assert count(db, "SELECT count(*) FROM weather_alerts") == 1


def test_past_alerts_end(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 10)
    run(hours(now, [5, -3] + [6] * 40), now)
    later = now + timedelta(days=3)
    run(hours(later, [6] * 48), later)
    assert count(db, "SELECT count(*) FROM weather_alerts WHERE status = 'past'") == 1


def test_weather_api_lists_active_alerts(client: TestClient) -> None:
    from garten_planer.routes.weather import get_influx

    setup_garden(client)
    now = datetime.now(TZ)
    run(hours(now, [5, -3] + [6] * 40), now) if now.month in (4, 5, 6, 7, 8, 9, 10) else None
    client.app.dependency_overrides[get_influx] = lambda: None  # type: ignore[attr-defined]
    w = client.get("/api/weather").json()
    assert w["available"] is False and isinstance(w["alerts"], list)


def test_alert_task_has_utc_safe_due_date(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 22)
    run(hours(now, [2, -3] + [6] * 40), now)  # frost in the night: the action is due the evening before
    with db.connect() as c:
        due = c.execute(text("SELECT due_date FROM tasks WHERE source = 'alert'")).scalar()
    assert due == date(2026, 10, 12)


# ----- review findings --------------------------------------------------------------------------


def test_no_false_all_clear_while_the_event_is_running(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 7, 10, 8)
    run(hours(now, [25, 28, 31, 33, 34, 33, 30] + [24] * 40), now)  # heat from 11:00
    later = at(
        2026,
        7,
        10,
        17,
    )
    assert run(hours(later, [29, 27, 25] + [22] * 40), later)["cancelled"] == 0  # evening: cooler, still that day
    assert count(db, "SELECT count(*) FROM weather_alerts WHERE status = 'active'") == 1
    assert count(db, "SELECT count(*) FROM push_messages") == 1
    next_day = at(2026, 7, 11, 8)
    assert run(hours(next_day, [22] * 48), next_day)["past"] == 1  # over: no all-clear push
    assert count(db, "SELECT count(*) FROM push_messages") == 1
    assert count(db, "SELECT count(*) FROM todos WHERE status = 'skipped' AND note = 'Warnung vorbei'") == 1


def test_frost_getting_strong_is_the_same_alert(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 10)
    run(hours(now, [5, 3, -9.5] + [6] * 40), now)
    assert run(hours(now, [5, 3, -10.5] + [6] * 40), now)["worse"] == 1
    assert count(db, "SELECT count(*) FROM weather_alerts") == 1
    assert count(db, "SELECT count(*) FROM weather_alerts WHERE kind = 'strong_frost'") == 1
    assert count(db, "SELECT count(*) FROM tasks WHERE source = 'alert' AND title LIKE 'Strenger Frost%'") == 2
    run(hours(now, [5, 3, -8] + [6] * 40), now)  # back to "frost": no all-clear, no new alert
    assert count(db, "SELECT count(*) FROM weather_alerts WHERE kind = 'frost' AND status = 'active'") == 1
    assert count(db, "SELECT count(*) FROM tasks WHERE source = 'alert' AND enabled") == 1  # Winterschutz gone
    assert count(db, "SELECT count(*) FROM push_messages") == 2


def test_alert_back_after_all_clear_gets_a_fresh_todo(client: TestClient, db: Engine) -> None:
    setup_garden(client)
    now = at(2026, 10, 12, 10)
    run(hours(now, [5, 3, -3] + [6] * 40), now)
    tid = client.get("/api/todos/heute").json()["open"][0]["id"]
    client.post(f"/api/todos/{tid}/done", json={}, headers=H)
    run(hours(now, [5, 3, 4] + [6] * 40), now)  # all-clear
    assert run(hours(now, [5, 3, -4] + [6] * 40), now)["created"] == 1  # back again
    open_ = [t for t in client.get("/api/todos/heute").json()["open"] if t["task"]["urgent"]]
    assert len(open_) == 1 and "4,0" in open_[0]["task"]["title"]


def test_due_date_stays_in_this_month() -> None:
    e = alerts.Event("frost", date(2026, 11, 2), -3, at(2026, 11, 2, 3))
    assert alerts.due(e, date(2026, 10, 31)) == date(2026, 10, 31)


def test_alerts_endpoint(client: TestClient) -> None:
    assert client.get("/api/alerts").json() == []


def test_silent_sensors_push_once_a_day(client: TestClient, db: Engine) -> None:
    from garten_planer.wetterwacht import check_sensor_feed

    setup_garden(client)

    class Fake:
        def __init__(self, last: str | None) -> None:
            self.last = last

        async def query(self, sql: str) -> list[dict[str, object]]:
            return [{"last": self.last}]

    def check(last: str | None, now: datetime) -> bool:
        async def go() -> bool:
            engine = create_async_engine(DATABASE_URL)
            try:
                return await check_sensor_feed(engine, Fake(last), now)  # type: ignore[arg-type]
            finally:
                await engine.dispose()

        return asyncio.run(go())

    now = at(2026, 11, 2, 12)
    assert check("2026-11-02T10:00:00", now) is False  # fresh
    assert check("2026-11-02T01:00:00", now) is True  # 11 h silent
    assert check("2026-11-02T01:00:00", now + timedelta(hours=3)) is False  # once a day
    assert check("2026-11-02T01:00:00", now + timedelta(hours=25)) is True  # still silent a day later
    with db.begin() as c:
        c.execute(text("DELETE FROM kv WHERE key IN ('sensors_seen', 'sensors_silent_push')"))
    assert check(None, now) is False  # never had sensors: nothing to watch
    assert count(db, "SELECT count(*) FROM push_messages") == 2
