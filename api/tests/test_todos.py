"""To-do engine over HTTP (F-TD): tasks create occurrences, the checklist
(done/undo/skip/postpone/note), interval follow-ups, calendar projection."""

from datetime import date, datetime, time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from garten_planer.routes.todos import TZ, now
from tests.conftest import BASE

H = {"Origin": BASE}
# task answer fields a PUT does not take
OUTPUT_ONLY = ("id", "plant", "enabled", "source", "notes", "products", "why", "next_due")
NOV_2 = date(2026, 11, 2)


@pytest.fixture
def plant_id(client: TestClient) -> str:
    st = client.post("/api/standorte", json={"name": "Weg", "light": "sonnig", "type": "beet"}, headers=H).json()
    body = {"species_id": "malus-domestica", "cultivar_id": "malus-domestica:sonate", "standort_id": st["id"]}
    return str(client.post("/api/plants", json=body, headers=H).json()["id"])


def on(client: TestClient, day: date) -> None:
    at = datetime.combine(day, time(10, 0), TZ)
    client.app.dependency_overrides[now] = lambda: at  # type: ignore[attr-defined]


def task(client: TestClient, **kw: Any) -> dict[str, Any]:
    body = {
        "title": "Fruchtmumien abnehmen",
        "category": "pflanzenschutz",
        "recurrence": "yearly",
        "month_from": 11,
        "month_to": 11,
        **kw,
    }
    r = client.post("/api/tasks", json=body, headers=H)
    assert r.status_code == 201, r.text
    return dict(r.json())


def heute(client: TestClient) -> dict[str, Any]:
    r = client.get("/api/todos/heute")
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_yearly_task_shows_up_in_its_month(client: TestClient, plant_id: str) -> None:
    on(client, NOV_2)
    t = task(client, plant_id=plant_id, instructions="Alle Mumien in den Restmüll.")
    h = heute(client)
    assert (h["year"], h["month"]) == (2026, 11)
    [todo] = h["open"]
    assert todo["task"]["id"] == t["id"] and todo["task"]["category"] == "pflanzenschutz"
    assert todo["plant"] == {"id": plant_id, "title": "Apfel \u2018Sonate\u2019"}
    assert (todo["due_from"], todo["due_to"], todo["overdue"]) == ("2026-11-01", "2026-11-30", False)
    assert heute(client)["open"] == h["open"]  # reading twice creates nothing twice


def test_done_with_note_then_undo(client: TestClient, plant_id: str) -> None:
    on(client, NOV_2)
    task(client, plant_id=plant_id)
    [todo] = heute(client)["open"]
    r = client.post(f"/api/todos/{todo['id']}/done", json={"note": "12 Stück"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "done"
    h = heute(client)
    assert h["open"] == [] and h["done"][0]["note"] == "12 Stück" and h["done"][0]["done_at"]
    client.post(f"/api/todos/{todo['id']}/undo", headers=H)
    h = heute(client)
    assert [x["id"] for x in h["open"]] == [todo["id"]] and h["done"] == []
    assert h["open"][0]["note"] == "12 Stück"  # the note is kept


def test_skip_and_postpone(client: TestClient) -> None:
    on(client, NOV_2)
    task(client, title="A")
    task(client, title="B")
    a, b = sorted(heute(client)["open"], key=lambda x: x["task"]["title"])
    assert client.post(f"/api/todos/{a['id']}/skip", json={}, headers=H).json()["status"] == "skipped"
    r = client.post(f"/api/todos/{b['id']}/postpone", json={"to": "2026-12-05"}, headers=H)
    assert (r.json()["due_from"], r.json()["postponed"]) == ("2026-12-05", True)
    h = heute(client)
    assert h["open"] == []  # B is now due in December
    assert [x["status"] for x in h["done"]] == ["skipped"]
    assert client.post(f"/api/todos/{b['id']}/postpone", json={"to": "2026-11-01"}, headers=H).status_code == 422


def test_interval_creates_the_next_one_after_done(client: TestClient, plant_id: str) -> None:
    on(client, NOV_2)
    task(
        client,
        plant_id=plant_id,
        title="Leimring prüfen",
        recurrence="interval",
        interval_days=7,
        month_from=None,
        month_to=None,
    )
    [first] = heute(client)["open"]
    client.post(f"/api/todos/{first['id']}/done", json={}, headers=H)
    [nxt] = heute(client)["open"]
    assert (nxt["due_from"], nxt["due_to"]) == ("2026-11-09", "2026-11-10")
    client.post(f"/api/todos/{first['id']}/undo", headers=H)  # undo removes the follow-up again
    assert [x["id"] for x in heute(client)["open"]] == [first["id"]]


def test_overdue_first_then_urgent(client: TestClient) -> None:
    on(client, NOV_2)
    task(client, title="normal")
    task(client, title="dringend", urgent=True)
    task(client, title="vergessen", recurrence="once", due_date="2026-10-01", month_from=None, month_to=None)
    titles = [x["task"]["title"] for x in heute(client)["open"]]
    assert titles == ["vergessen", "dringend", "normal"]
    assert heute(client)["open"][0]["overdue"] is True


def test_changing_the_window_replaces_open_but_keeps_done(client: TestClient) -> None:
    on(client, NOV_2)
    t = task(client)
    [todo] = heute(client)["open"]
    client.post(f"/api/todos/{todo['id']}/done", json={}, headers=H)
    on(client, date(2027, 1, 10))
    body = {**t, "month_from": 1, "month_to": 1}
    for k in OUTPUT_ONLY:
        body.pop(k)
    assert client.put(f"/api/tasks/{t['id']}", json=body, headers=H).status_code == 200
    h = heute(client)
    assert [x["due_from"] for x in h["open"]] == ["2027-01-01"]


def test_disable_removes_open_occurrences(client: TestClient) -> None:
    on(client, NOV_2)
    t = task(client)
    assert client.post(f"/api/tasks/{t['id']}/disable", headers=H).json()["enabled"] is False
    assert heute(client)["open"] == []
    assert client.post(f"/api/tasks/{t['id']}/enable", headers=H).json()["enabled"] is True
    assert len(heute(client)["open"]) == 1


def test_calendar_projects_tasks_per_month(client: TestClient, plant_id: str) -> None:
    task(client, plant_id=plant_id, title="Winterschutz", category="winterschutz", month_from=11, month_to=2)
    r = client.get("/api/calendar", params={"year": 2026})
    months = r.json()["months"]
    assert len(months) == 12
    assert [m for m in range(12) if months[m]] == [0, 1, 10, 11]
    assert months[10][0]["title"] == "Winterschutz" and months[10][0]["plant"]["id"] == plant_id


def test_list_tasks_of_a_plant(client: TestClient, plant_id: str) -> None:
    task(client, plant_id=plant_id, title="A")
    task(client, title="Garten allgemein")
    assert [t["title"] for t in client.get("/api/tasks", params={"plant_id": plant_id}).json()] == ["A"]
    assert len(client.get("/api/tasks").json()) == 2


@pytest.mark.parametrize(
    "bad",
    [
        {"month_from": None},  # yearly needs both months
        {"month_to": 13},
        {"recurrence": "once", "month_from": None, "month_to": None},  # once needs a date
        {"recurrence": "interval", "interval_days": 0, "month_from": None, "month_to": None},
        {"category": "giessen"},  # never watering in the garden (F-CP-6)
        {"title": ""},
        {"title": "x" * 121},
        {"instructions": "x" * 4001},
        {"plant_id": "nope"},
    ],
)
def test_validation(client: TestClient, bad: dict[str, Any]) -> None:
    body = {
        "title": "T",
        "category": "schnitt",
        "cut_type": "pflege",
        "recurrence": "yearly",
        "month_from": 2,
        "month_to": 2,
        **bad,
    }
    assert client.post("/api/tasks", json=body, headers=H).status_code == 422


def test_unknown_ids_are_404(client: TestClient) -> None:
    assert client.post("/api/todos/nope/done", json={}, headers=H).status_code == 404
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.post("/api/tasks/nope/disable", headers=H).status_code == 404


# ----- review M3a: the scenarios that broke the first design -------------------


def interval_task(client: TestClient, plant_id: str | None = None, days: int = 7) -> dict[str, Any]:
    return task(client, plant_id=plant_id, title="Leimring prüfen", recurrence="interval", interval_days=days,
                month_from=None, month_to=None)  # fmt: skip


def edit_task(client: TestClient, t: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = {k: v for k, v in t.items() if k not in OUTPUT_ONLY} | changes
    r = client.put(f"/api/tasks/{t['id']}", json=body, headers=H)
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_interval_survives_pause_and_resume(client: TestClient) -> None:
    on(client, NOV_2)
    t = interval_task(client)
    [first] = heute(client)["open"]
    client.post(f"/api/todos/{first['id']}/done", json={}, headers=H)
    client.post(f"/api/tasks/{t['id']}/disable", headers=H)
    client.post(f"/api/tasks/{t['id']}/enable", headers=H)
    assert [x["due_from"] for x in heute(client)["open"]] == ["2026-11-09"]  # last done + 7


def test_history_is_never_deleted(client: TestClient) -> None:
    on(client, NOV_2)
    t = interval_task(client)
    [a] = heute(client)["open"]
    client.post(f"/api/todos/{a['id']}/done", json={}, headers=H)
    on(client, date(2026, 11, 9))
    [b] = heute(client)["open"]
    client.post(f"/api/todos/{b['id']}/done", json={"note": "B erledigt"}, headers=H)
    client.post(f"/api/todos/{a['id']}/undo", headers=H)
    client.post(f"/api/tasks/{t['id']}/disable", headers=H)
    assert client.get(f"/api/todos/{b['id']}").json()["note"] == "B erledigt"


def test_archived_plants_produce_no_todos(client: TestClient, plant_id: str) -> None:
    on(client, NOV_2)
    task(client, plant_id=plant_id)
    client.post(f"/api/plants/{plant_id}/archive", headers=H)
    assert heute(client)["open"] == []
    assert not any(client.get("/api/calendar", params={"year": 2026}).json()["months"])
    client.post(f"/api/plants/{plant_id}/restore", headers=H)
    assert len(heute(client)["open"]) == 1


def test_changing_the_interval_counts_from_the_last_done_day(client: TestClient) -> None:
    on(client, NOV_2)
    t = interval_task(client)
    [a] = heute(client)["open"]
    client.post(f"/api/todos/{a['id']}/done", json={}, headers=H)
    on(client, date(2026, 11, 4))
    edit_task(client, t, interval_days=14)
    assert [x["due_from"] for x in heute(client)["open"]] == ["2026-11-16"]  # Nov 2 + 14, not "today"


def test_new_window_after_done_still_creates_an_occurrence(client: TestClient) -> None:
    on(client, NOV_2)
    t = task(client)
    [a] = heute(client)["open"]
    client.post(f"/api/todos/{a['id']}/done", json={}, headers=H)
    edit_task(client, t, month_from=12, month_to=12)
    assert client.get("/api/calendar", params={"year": 2026}).json()["months"][11]
    on(client, date(2026, 12, 3))
    assert [x["due_from"] for x in heute(client)["open"]] == ["2026-12-01"]


def test_undo_of_an_item_from_before_a_change_is_refused(client: TestClient) -> None:
    on(client, NOV_2)
    t = task(client)
    [a] = heute(client)["open"]
    client.post(f"/api/todos/{a['id']}/done", json={}, headers=H)
    edit_task(client, t, month_from=12, month_to=12)
    assert client.post(f"/api/todos/{a['id']}/undo", headers=H).status_code == 409


def test_only_the_newest_open_occurrence_per_task(client: TestClient) -> None:
    on(client, NOV_2)
    task(client)
    on(client, date(2027, 11, 2))  # last year's one was never done
    [only] = heute(client)["open"]
    assert only["due_from"] == "2027-11-01"


@pytest.mark.parametrize("field", ["due_date", "start_date"])
def test_dates_are_bounded(client: TestClient, field: str) -> None:
    rec = "once" if field == "due_date" else "interval"
    body = {"title": "T", "category": "duengen", "recurrence": rec, "interval_days": 1, field: "0001-01-01"}
    assert client.post("/api/tasks", json=body, headers=H).status_code == 422


def test_calendar_is_fast_for_daily_tasks_far_back(client: TestClient) -> None:
    task(client, recurrence="interval", interval_days=1, start_date="2000-01-01", month_from=None, month_to=None)
    r = client.get("/api/calendar", params={"year": 2100})
    assert r.status_code == 200 and all(r.json()["months"])
