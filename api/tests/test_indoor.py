"""Indoor plants (M11, F-IN): Standort drinnen (type zimmer), window and pot on the plant,
watering only indoors, seasonal intervals (winter rhythm, active months), soil feedback,
no § 39 / weather rules indoors, the indoor care plan and plant ID by photo."""

import asyncio
import io
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import create_async_engine

from garten_planer import plan
from garten_planer.routes.todos import TZ, now
from garten_planer.schedule import TaskTiming, interval_after, occurrences
from garten_planer.worker import run_name_jobs
from tests.conftest import BASE, DATABASE_URL

H = {"Origin": BASE}
NOV_2 = date(2026, 11, 2)
INDOOR = {"window_dir": "S", "window_distance": "bis_1m", "pot_cm": 18, "pot_material": "ton"}
ROOM_WINDOWS = ["O", "S"]


def on(client: TestClient, day: date) -> None:
    at = datetime.combine(day, time(10, 0), TZ)
    client.app.dependency_overrides[now] = lambda: at  # type: ignore[attr-defined]


def standort(client: TestClient, typ: str, name: str) -> str:
    light = None if typ == "zimmer" else "halbschattig"
    windows = ROOM_WINDOWS if typ == "zimmer" else []
    r = client.post("/api/standorte", json={"name": name, "light": light, "type": typ, "windows": windows}, headers=H)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def plant(client: TestClient, sid: str, **kw: Any) -> dict[str, Any]:
    r = client.post("/api/plants", json={"species_id": "malus-domestica", "standort_id": sid, **kw}, headers=H)
    assert r.status_code == 201, r.text
    return dict(r.json())


def water(client: TestClient, pid: str, **kw: Any) -> Any:
    body = {"title": "Gießen", "category": "giessen", "recurrence": "interval", "interval_days": 7,
            "plant_id": pid, **kw}  # fmt: skip
    return client.post("/api/tasks", json=body, headers=H)


def open_todo(client: TestClient, task_id: str) -> dict[str, Any] | None:
    return next((t for t in client.get("/api/todos/heute").json()["open"] if t["task"]["id"] == task_id), None)


# ----- model ---------------------------------------------------------------------------------------


def test_indoor_plant_keeps_window_and_pot(client: TestClient) -> None:
    p = plant(client, standort(client, "zimmer", "Wohnzimmer"), **INDOOR)
    got = client.get(f"/api/plants/{p['id']}").json()
    assert {k: got[k] for k in INDOOR} == INDOOR
    assert got["standort"]["indoor"] is True


def test_a_room_has_no_light_outdoors_needs_it(client: TestClient) -> None:
    r = client.post("/api/standorte", json={"name": "Bad", "light": "sonnig", "type": "zimmer"}, headers=H)
    assert r.status_code == 201 and r.json()["light"] is None  # ignored: the window on the plant counts
    assert client.post("/api/standorte", json={"name": "Beet", "type": "beet"}, headers=H).status_code == 422


def test_windows_belong_to_the_room(client: TestClient) -> None:
    r = client.post("/api/standorte", json={"name": "Eckzimmer", "type": "zimmer", "windows": ["W", "S", "S"]},
                    headers=H)  # fmt: skip
    assert r.json()["windows"] == ["S", "W"]  # sorted N, O, S, W; once each
    p = plant(client, r.json()["id"], window_distance="1_2m")
    assert client.get(f"/api/plants/{p['id']}").json()["standort"]["windows"] == ["S", "W"]
    bad = {"species_id": "malus-domestica", "standort_id": r.json()["id"], "window_dir": "N"}
    assert client.post("/api/plants", json=bad, headers=H).status_code == 422  # no north window in that room
    garden = client.post("/api/standorte", json={"name": "Wiese", "light": "sonnig", "type": "rasen", "windows": ["S"]},
                         headers=H)  # fmt: skip
    assert garden.json()["windows"] == []


def test_window_and_pot_only_indoors(client: TestClient) -> None:
    sid = standort(client, "beet", "Beet")
    r = client.post("/api/plants", json={"species_id": "malus-domestica", "standort_id": sid, **INDOOR}, headers=H)
    assert r.status_code == 422


def test_standort_cannot_switch_inside_out_with_plants(client: TestClient) -> None:
    sid = standort(client, "zimmer", "Büro")
    plant(client, sid)
    r = client.put(f"/api/standorte/{sid}", json={"name": "Büro", "light": "sonnig", "type": "beet"}, headers=H)
    assert r.status_code == 409
    ok = client.put(f"/api/standorte/{sid}", json={"name": "Arbeitszimmer", "type": "zimmer"},
                    headers=H)  # fmt: skip
    assert ok.status_code == 200


# ----- watering only indoors --------------------------------------------------------------------------


def test_watering_only_for_indoor_plants(client: TestClient) -> None:
    on(client, NOV_2)
    inside = plant(client, standort(client, "zimmer", "Bad"))
    outside = plant(client, standort(client, "beet", "Beet"))
    assert water(client, inside["id"]).status_code == 201
    assert water(client, outside["id"]).status_code == 422
    assert water(client, None).status_code == 422


@pytest.mark.parametrize("category", ["bespruehen", "entstauben"])
def test_misting_and_dusting_only_indoors(client: TestClient, category: str) -> None:
    on(client, NOV_2)
    inside = plant(client, standort(client, "zimmer", "Atelier"))
    outside = plant(client, standort(client, "hecke", "Hecke"))
    assert water(client, inside["id"], category=category, title="Pflege").status_code == 201
    assert water(client, outside["id"], category=category, title="Pflege").status_code == 422


def test_moving_outside_pauses_watering(client: TestClient) -> None:
    on(client, NOV_2)
    p = plant(client, standort(client, "zimmer", "Flur"))
    tid = water(client, p["id"]).json()["id"]
    garden = standort(client, "kuebelplatz", "Terrasse")
    r = client.put(f"/api/plants/{p['id']}", json={"species_id": "malus-domestica", "standort_id": garden}, headers=H)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/tasks/{tid}").json()["enabled"] is False
    assert open_todo(client, tid) is None


# ----- seasonal intervals ---------------------------------------------------------------------------------


def test_winter_rhythm_and_active_months() -> None:
    t = TaskTiming("interval", interval_days=7, winter_interval_days=14)
    assert interval_after(date(2026, 11, 2), t).due_from == date(2026, 11, 16)  # winter: every 14 days
    assert interval_after(date(2026, 5, 2), t).due_from == date(2026, 5, 9)
    feed = TaskTiming("interval", interval_days=28, month_from=4, month_to=9)
    assert interval_after(date(2026, 9, 20), feed).due_from == date(2027, 4, 1)  # October: rest until April
    assert occurrences(feed, NOV_2) == []  # not before April (beyond the horizon)
    assert occurrences(feed, date(2027, 3, 20))[0].due_from == date(2027, 4, 1)


def test_watering_follows_the_winter_rhythm(client: TestClient) -> None:
    on(client, NOV_2)
    p = plant(client, standort(client, "zimmer", "Küche"))
    t = water(client, p["id"], winter_interval_days=14).json()
    assert t["winter_interval_days"] == 14
    todo = open_todo(client, t["id"])
    assert todo is not None
    client.post(f"/api/todos/{todo['id']}/done", json={}, headers=H)
    nxt = open_todo(client, t["id"])
    assert nxt is not None and nxt["due_from"] == (NOV_2 + timedelta(days=14)).isoformat()


def test_interval_months_need_both_ends(client: TestClient) -> None:
    p = plant(client, standort(client, "zimmer", "Diele"))
    r = water(client, p["id"], category="duengen", title="Düngen", month_from=4)
    assert r.status_code == 422


# ----- soil feedback ----------------------------------------------------------------------------------


def test_reenabling_watering_outside_is_refused(client: TestClient) -> None:
    on(client, NOV_2)
    p = plant(client, standort(client, "zimmer", "Lesezimmer"))
    tid = water(client, p["id"], category="bespruehen", title="Besprühen").json()["id"]
    garden = standort(client, "beet", "Hochbeet")
    client.put(f"/api/plants/{p['id']}", json={"species_id": "malus-domestica", "standort_id": garden}, headers=H)
    assert client.get(f"/api/tasks/{tid}").json()["enabled"] is False  # misting paused too
    assert client.post(f"/api/tasks/{tid}/enable", headers=H).status_code == 422
    assert open_todo(client, tid) is None


def test_no_watering_todos_for_a_plant_that_is_outside(client: TestClient, db: Engine) -> None:
    """Whatever wrote the task (a plan that finished after the move, an old row): no to-do outside."""
    on(client, NOV_2)
    p = plant(client, standort(client, "beet", "Rabatte"))
    with db.begin() as c:
        c.exec_driver_sql(
            "INSERT INTO tasks (id, plant_id, title, category, instructions, recurrence, interval_days, urgent,"
            " source, enabled, generation, created_at, updated_at) VALUES ('t-w', %s, 'Gießen', 'giessen', '',"
            " 'interval', 7, false, 'plan', true, 1, now(), now())", (p["id"],))  # fmt: skip
    assert open_todo(client, "t-w") is None


def test_rhythm_follows_the_next_date() -> None:
    from garten_planer.schedule import rhythm_field

    t = TaskTiming("interval", interval_days=7, winter_interval_days=21)
    assert rhythm_field(date(2026, 10, 28), t) == "winter_interval_days"  # next one in November
    assert rhythm_field(date(2026, 2, 25), t) == "interval_days"  # next one in March


def test_seasonal_calendar_projection() -> None:
    from garten_planer.schedule import months_in_year

    repot = TaskTiming("interval", interval_days=730, month_from=3, month_to=4, start_date=date(2026, 10, 1))
    assert months_in_year(repot, 2027) == [3]


@pytest.mark.parametrize(("soil", "summer", "winter"), [("feucht", 7, 17), ("passt", 7, 14), ("trocken", 7, 11)])
def test_soil_feedback_adjusts_the_rhythm(client: TestClient, soil: str, summer: int, winter: int) -> None:
    on(client, NOV_2)  # winter: the winter rhythm changes
    p = plant(client, standort(client, "zimmer", "Esszimmer"))
    t = water(client, p["id"], winter_interval_days=14).json()
    todo = open_todo(client, t["id"])
    assert todo is not None
    client.post(f"/api/todos/{todo['id']}/done", json={}, headers=H)
    r = client.post(f"/api/todos/{todo['id']}/soil", json={"soil": soil}, headers=H)
    assert r.status_code == 200, r.text
    task = client.get(f"/api/tasks/{t['id']}").json()
    assert (task["interval_days"], task["winter_interval_days"]) == (summer, winter)
    nxt = open_todo(client, t["id"])
    assert nxt is not None and nxt["due_from"] == (NOV_2 + timedelta(days=winter)).isoformat()
    assert client.post(f"/api/todos/{todo['id']}/soil", json={"soil": soil}, headers=H).status_code == 409


def test_soil_feedback_bounds_and_only_for_watering(client: TestClient) -> None:
    on(client, date(2026, 6, 1))
    p = plant(client, standort(client, "zimmer", "Kinderzimmer"))
    t = water(client, p["id"], interval_days=2).json()
    todo = open_todo(client, t["id"])
    assert todo is not None
    client.post(f"/api/todos/{todo['id']}/done", json={}, headers=H)
    client.post(f"/api/todos/{todo['id']}/soil", json={"soil": "trocken"}, headers=H)
    assert client.get(f"/api/tasks/{t['id']}").json()["interval_days"] == 2  # never below 2 days
    other = client.post("/api/tasks", json={"title": "Topf drehen", "category": "sonstiges", "recurrence": "interval",
                                            "interval_days": 30, "plant_id": p["id"]}, headers=H).json()  # fmt: skip
    o = open_todo(client, other["id"])
    assert o is not None
    client.post(f"/api/todos/{o['id']}/done", json={}, headers=H)
    assert client.post(f"/api/todos/{o['id']}/soil", json={"soil": "feucht"}, headers=H).status_code == 409


# ----- garden rules do not apply indoors ------------------------------------------------------------------------


def test_no_bird_protection_period_indoors(client: TestClient) -> None:
    on(client, date(2026, 5, 10))  # inside the § 39 period
    p = plant(
        client,
        standort(client, "zimmer", "Wintergarten"),
    )
    body = {"title": "Stark zurückschneiden", "category": "schnitt", "cut_type": "stark", "recurrence": "once",
            "due_date": "2026-05-12", "plant_id": p["id"]}  # fmt: skip
    t = client.post("/api/tasks", json=body, headers=H).json()
    todo = open_todo(client, t["id"])
    assert todo is not None and todo["due_from"] == "2026-05-12" and todo["blocked_until"] is None


def test_weather_watch_ignores_indoor_plants(client: TestClient, db: Engine) -> None:
    from garten_planer.wetterwacht import garden_plants

    plant(client, standort(client, "zimmer", "Gästezimmer"), nickname="Drinnen")
    plant(client, standort(client, "kuebelplatz", "Balkon"), nickname="Draussen", in_container=True)

    async def go() -> list[Any]:
        engine = create_async_engine(DATABASE_URL)
        try:
            async with engine.connect() as c:
                return await garden_plants(c)
        finally:
            await engine.dispose()

    assert [p.title for p in asyncio.run(go())] == ["Draussen"]


# ----- indoor care plan -------------------------------------------------------------------------------------------


def _raw(*tasks: dict[str, Any]) -> dict[str, Any]:
    return {"summary": "Pflege", "confidence": "high", "caveats": "", "pests": [], "tasks": list(tasks)}


WATER_TASK = {"title": "Gießen", "category": "giessen", "recurrence": "interval", "interval_days": 21,
              "winter_interval_days": 35, "instructions": "Durchdringend gießen."}  # fmt: skip


def test_indoor_plan_keeps_watering_garden_plan_drops_it() -> None:
    feed = {"title": "Düngen", "category": "duengen", "recurrence": "interval", "interval_days": 28,
            "month_from": 4, "month_to": 9, "pheno_phase": "erstfruehling"}  # fmt: skip
    indoor = plan.sanitize(_raw(WATER_TASK, feed), indoor=True)
    assert [(t.category, t.winter_interval_days) for t in indoor.tasks] == [("giessen", 35), ("duengen", None)]
    assert indoor.tasks[1].pheno_phase is None and (indoor.tasks[1].month_from, indoor.tasks[1].month_to) == (4, 9)
    mist = {"title": "Blätter besprühen", "category": "bespruehen", "recurrence": "interval", "interval_days": 3}
    garden = plan.sanitize(_raw(WATER_TASK, feed, mist), indoor=False)
    assert [t.category for t in garden.tasks] == ["duengen"] and garden.dropped == 2
    assert [t.category for t in plan.sanitize(_raw(mist), indoor=True).tasks] == ["bespruehen"]


def test_indoor_prompt_has_window_and_pot() -> None:
    f = plan.PlanFacts(latin="Beaucarnea recurvata", german="Elefantenfuß", cultivar=None, form=None, rootstock=None,
                       planted_year=None, in_container=True, light=None, standort_type="zimmer", bundesland=None,
                       fertiliser="egal", eco_defaults=True, window="S", window_distance="bis_1m", pot_cm=18,
                       pot_material="ton")  # fmt: skip
    prompt = plan.build_prompt(f)
    assert '"fenster_richtung": "S"' in prompt and '"topf_cm": 18' in prompt
    assert plan.system_for(f) is plan.SYSTEM_INDOOR and "giessen" in plan.SYSTEM_INDOOR


# ----- plant ID by photo --------------------------------------------------------------------------------------------


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (60, 120, 50)).save(buf, "JPEG")
    return buf.getvalue()


def test_plant_id_by_photo(client: TestClient) -> None:
    pid = client.post("/api/photos", content=_jpeg(), headers={**H, "Content-Type": "image/jpeg"}).json()["id"]
    r = client.post("/api/species/ai", json={"photo_ids": [pid]}, headers=H)
    assert r.status_code == 202, r.text
    seen: list[tuple[str, list[bytes]]] = []

    async def runner(prompt: str, system: str, schema: dict[str, Any], images: list[bytes] | None = None) -> Any:
        seen.append((prompt, images or []))
        return {"candidates": [{"latin": "Beaucarnea recurvata", "german": ["Elefantenfuß"], "family": "Asparagaceae",
                                "growth": "kuebel", "woody": True, "cultivar": None, "form_hint": None,
                                "winterhaerte_c": 5, "note": "ziemlich sicher"}]}, {"model": "m"}  # fmt: skip

    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_name_jobs(engine, runner, daily_limit=50)
        finally:
            await engine.dispose()

    asyncio.run(go())
    assert len(seen[0][1]) == 1 and seen[0][1][0][:2] == b"\xff\xd8" and "Foto" in seen[0][0]
    job = client.get(f"/api/species/ai/{r.json()['job_id']}").json()
    assert job["status"] == "done" and job["candidates"][0]["latin"] == "Beaucarnea recurvata"
    again = client.post("/api/species/ai", json={"photo_ids": [pid]}, headers=H)  # photos are used once
    assert again.status_code == 422


def test_name_lookup_needs_text_or_photo(client: TestClient) -> None:
    assert client.post("/api/species/ai", json={}, headers=H).status_code == 422
