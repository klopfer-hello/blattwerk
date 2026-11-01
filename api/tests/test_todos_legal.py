"""Legal rules inside the to-do engine (M4): cut type required for Schnitt, strong
cuts of hedges/shrubs moved out of the bird-protection period with the reason
stored, notes on tasks and to-dos, calendar shows the moved month, form preview."""

from datetime import date, datetime, time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from blattwerk.routes.todos import TZ, now
from tests.conftest import BASE

H = {"Origin": BASE}
# task answer fields a PUT does not take
OUTPUT_ONLY = ("id", "plant", "enabled", "source", "notes", "products", "why", "next_due")


def on(client: TestClient, day: date) -> None:
    at = datetime.combine(day, time(10, 0), TZ)
    client.app.dependency_overrides[now] = lambda: at  # type: ignore[attr-defined]


def plant(client: TestClient, species_id: str, **kw: Any) -> str:
    st = client.post("/api/standorte", json={"name": "Nord", "light": "sonnig", "type": "hecke"}, headers=H).json()
    body = {"species_id": species_id, "standort_id": st["id"], **kw}
    r = client.post("/api/plants", json=body, headers=H)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def cut(
    client: TestClient, plant_id: str | None, cut_type: str = "stark", m_from: int = 6, m_to: int = 6
) -> dict[str, Any]:
    body = {"title": "Hecke zurückschneiden", "category": "schnitt", "cut_type": cut_type, "recurrence": "yearly",
            "month_from": m_from, "month_to": m_to, "plant_id": plant_id}  # fmt: skip
    r = client.post("/api/tasks", json=body, headers=H)
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_strong_hedge_cut_in_june_is_moved_to_october(client: TestClient) -> None:
    on(client, date(2026, 6, 10))
    hedge = plant(client, "carpinus-betulus")
    cut(client, hedge)
    assert client.get("/api/todos/heute").json()["open"] == []  # nothing in June
    on(client, date(2026, 10, 2))
    [todo] = client.get("/api/todos/heute").json()["open"]
    assert (todo["due_from"], todo["due_to"]) == ("2026-10-01", "2026-10-31")
    assert "§ 39" in todo["legal_adjustment"]
    assert {n["code"] for n in todo["notes"]} >= {"para39-strong", "para44"}


def test_gentle_cut_stays_in_june_with_notes(client: TestClient) -> None:
    on(client, date(2026, 6, 10))
    cut(client, plant(client, "carpinus-betulus"), cut_type="pflege")
    [todo] = client.get("/api/todos/heute").json()["open"]
    assert todo["due_from"] == "2026-06-01" and todo["legal_adjustment"] is None
    assert {n["code"] for n in todo["notes"]} == {"para39-gentle", "para44"}


def test_garden_trees_are_not_moved(client: TestClient) -> None:
    on(client, date(2026, 6, 10))
    cut(client, plant(client, "malus-domestica"))
    [todo] = client.get("/api/todos/heute").json()["open"]
    assert todo["due_from"] == "2026-06-01" and todo["legal_adjustment"] is None


def test_task_answer_and_calendar_carry_the_rules(client: TestClient) -> None:
    t = cut(client, plant(client, "carpinus-betulus"))
    assert "para39-strong" in {n["code"] for n in t["notes"]}
    months = client.get("/api/calendar", params={"year": 2026}).json()["months"]
    assert months[5] == []  # June: not allowed
    assert months[9][0]["moved"] is True  # shown in October


def test_baumschutz_note_uses_the_settings(client: TestClient) -> None:
    settings = client.get("/api/settings").json()
    settings["legal"] = {"baumschutz_girth_cm": 80, "fruit_trees_exempt": False}
    client.put("/api/settings", json=settings, headers=H)
    t = cut(client, plant(client, "malus-domestica", girth_cm=120), m_from=2, m_to=2)
    assert "baumschutz" in {n["code"] for n in t["notes"]}


@pytest.mark.parametrize(
    ("category", "cut_type"),
    [("schnitt", None), ("duengen", "stark"), ("schnitt", "radikal")],
)
def test_cut_type_only_and_always_for_schnitt(client: TestClient, category: str, cut_type: str | None) -> None:
    body = {
        "title": "T",
        "category": category,
        "cut_type": cut_type,
        "recurrence": "yearly",
        "month_from": 2,
        "month_to": 2,
    }
    assert client.post("/api/tasks", json=body, headers=H).status_code == 422


def test_preview_for_the_form(client: TestClient) -> None:
    on(client, date(2026, 5, 2))
    hedge = plant(client, "carpinus-betulus")
    body = {"title": "Hecke", "category": "schnitt", "cut_type": "stark", "recurrence": "yearly",
            "month_from": 5, "month_to": 5, "plant_id": hedge}  # fmt: skip
    r = client.post("/api/legal/preview", json=body, headers=H)
    assert r.status_code == 200
    p = r.json()
    assert "para39-strong" in {n["code"] for n in p["notes"]}
    assert p["next"]["due_from"] == "2026-10-01" and "§ 39" in p["next"]["reason"]


# ----- review M4: bypasses ----------------------------------------------------------


def test_postpone_into_the_closed_period_is_refused(client: TestClient) -> None:
    on(client, date(2026, 10, 5))
    cut(client, plant(client, "carpinus-betulus"), m_from=10, m_to=10)
    [todo] = client.get("/api/todos/heute").json()["open"]
    r = client.post(f"/api/todos/{todo['id']}/postpone", json={"to": "2027-04-15"}, headers=H)
    assert r.status_code == 422 and "§ 39" in r.json()["fields"]["to"]
    assert client.post(f"/api/todos/{todo['id']}/postpone", json={"to": "2026-11-15"}, headers=H).status_code == 200


def test_switching_to_a_strong_cut_moves_the_open_todo(client: TestClient) -> None:
    on(client, date(2026, 6, 10))
    t = cut(client, plant(client, "carpinus-betulus"), cut_type="pflege")
    assert len(client.get("/api/todos/heute").json()["open"]) == 1
    body = {k: v for k, v in t.items() if k not in OUTPUT_ONLY} | {"cut_type": "stark"}
    assert client.put(f"/api/tasks/{t['id']}", json=body, headers=H).status_code == 200
    assert client.get("/api/todos/heute").json()["open"] == []  # now only in October


def test_overdue_strong_cut_is_not_shown_as_overdue_in_summer(client: TestClient) -> None:
    on(client, date(2026, 2, 3))
    cut(client, plant(client, "carpinus-betulus"), m_from=1, m_to=2)
    on(client, date(2026, 4, 2))
    [todo] = client.get("/api/todos/heute").json()["open"]
    assert todo["overdue"] is False and todo["blocked_until"] == "2026-10-01"


def test_calendar_matches_what_is_created(client: TestClient) -> None:
    cut(client, plant(client, "carpinus-betulus"), m_from=2, m_to=10)
    months = client.get("/api/calendar", params={"year": 2026}).json()["months"]
    assert [m for m in range(12) if months[m]] == [1]  # only February, like adjust_window
    assert months[1][0]["moved"] is False  # February is the original month
