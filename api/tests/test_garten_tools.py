"""The garden chat's tools (M8, F-AI-4): what Claude can read about the garden (and what
never: Ort, PLZ, plant notes), and that writing only creates proposals the user confirms."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from garten_planer import garten_tools as gt
from garten_planer.routes.todos import TZ, now
from tests.conftest import BASE, DATABASE_URL

H = {"Origin": BASE}
SOON = (date.today() + timedelta(days=3)).isoformat()
PAST = (date.today() - timedelta(days=3)).isoformat()


def call(fn: Callable[..., Awaitable[Any]], *args: Any, **kw: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(DATABASE_URL)
        try:
            async with engine.begin() as c:
                return await fn(c, *args, **kw)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def garden(client: TestClient) -> str:
    s = client.get("/api/settings").json()
    s["location"] = s["location"] | {"plz": "12345", "ort": "Geheimstadt", "bundesland": "Sachsen"}
    assert client.put("/api/settings", json=s, headers=H).status_code == 200
    st = client.post("/api/standorte", json={"name": "Terrasse", "light": "sonnig", "type": "kuebelplatz",
                                             "notes": "Nachbar hinten"}, headers=H).json()  # fmt: skip
    body = {"species_id": "malus-domestica", "standort_id": st["id"], "nickname": "Kübelapfel", "in_container": True,
            "planted_year": 2021, "notes": "Privat: Geschenk von Oma"}  # fmt: skip
    return str(client.post("/api/plants", json=body, headers=H).json()["id"])


def test_overview_has_the_garden_but_nothing_personal(client: TestClient) -> None:
    pid = garden(client)
    o = call(gt.ueberblick, date(2026, 10, 31))
    dump = json.dumps(o, ensure_ascii=False)
    assert o["bundesland"] == "Sachsen" and o["standorte"][0]["pflanzen"][0]["id"] == pid
    assert "Kübelapfel" in dump and "Apfel" in dump
    for private in ("Geheimstadt", "12345", "Oma", "Nachbar"):
        assert private not in dump


def test_plant_detail_and_unknown_plant(client: TestClient) -> None:
    pid = garden(client)
    p = call(gt.pflanze, pid, date(2026, 10, 31))
    assert p["name"] == "Kübelapfel" and p["im_kuebel"] is True and "notizen" not in p
    assert "Oma" not in json.dumps(p, ensure_ascii=False)
    assert call(gt.pflanze, "nope", date(2026, 10, 31)) == {"fehler": "Pflanze nicht gefunden"}


def test_tasks_of_the_month(client: TestClient) -> None:
    client.app.dependency_overrides[now] = lambda: datetime.combine(date(2026, 10, 10), time(10), TZ)  # type: ignore[attr-defined]
    pid = garden(client)
    body = {"title": "Leimringe anbringen", "category": "pflanzenschutz", "recurrence": "yearly", "month_from": 10,
            "month_to": 10, "plant_id": pid}  # fmt: skip
    client.post("/api/tasks", json=body, headers=H)
    a = call(gt.aufgaben, date(2026, 10, 10))
    assert [x["titel"] for x in a["offen"]] == ["Leimringe anbringen"] and a["offen"][0]["pflanze"] == "Kübelapfel"


def test_proposals_are_stored_not_carried_out(client: TestClient, db: Engine) -> None:
    pid = garden(client)
    mid = chat_message(db)
    r = call(gt.aufgabe_vorschlagen, mid, "Kübel ins Haus holen", SOON, pid, "Vor dem Frost.")
    assert r["vorgeschlagen"] is True
    r2 = call(gt.notiz_vorschlagen, mid, pid, "Hat dieses Jahr gut getragen.")
    assert r2["vorgeschlagen"] is True
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM chat_actions WHERE status = 'proposed'")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM tasks")).scalar() == 0  # nothing done yet


@pytest.mark.parametrize(
    ("title", "day"),
    [("", "2026-11-03"), ("Gießen", "2026-11-03"), ("Kübel rein", "kein Datum"), ("x" * 200, "2026-11-03")],
)
def test_bad_proposals_are_refused(client: TestClient, db: Engine, title: str, day: str) -> None:
    mid = chat_message(db)
    r = call(gt.aufgabe_vorschlagen, mid, title, day, None, "")
    assert "fehler" in r


def chat_message(db: Engine) -> str:
    with db.begin() as c:
        c.execute(text("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 'Test', now(), now())"))
        c.execute(text("INSERT INTO chat_messages (id, chat_id, role, text, status, created_at) "
                       "VALUES ('m1', 'c1', 'assistant', '', 'running', now())"))  # fmt: skip
    return "m1"


def test_mcp_server_lists_exactly_the_garden_tools() -> None:
    from garten_planer.mcp_garten import build

    tools = asyncio.run(build().list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["aufgabe_vorschlagen", "aufgaben", "garten_ueberblick", "jahreszeit", "notiz_vorschlagen",
                     "pflanze", "verlauf", "wetter"]  # fmt: skip
    assert not any("loesch" in n or "delete" in n for n in names)


def test_a_cut_proposed_by_the_chat_goes_through_paragraph_39(client: TestClient, db: Engine) -> None:
    mid = chat_message(db)
    call(gt.aufgabe_vorschlagen, mid, "Hecke radikal zurückschneiden", SOON, None, "", "sonstiges")
    call(gt.aufgabe_vorschlagen, mid, "Rosen in Form schneiden", SOON, None, "", "schnitt", "pflege")
    with db.connect() as c:
        kinds = sorted(c.execute(text("SELECT payload->>'category', payload->>'cut_type' FROM chat_actions")).all())
    assert kinds == [("schnitt", "pflege"), ("schnitt", "stark")]


def test_proposals_per_answer_are_capped_and_deduplicated(client: TestClient, db: Engine) -> None:
    mid = chat_message(db)
    for i in range(7):
        call(gt.aufgabe_vorschlagen, mid, f"Aufgabe {i % 6}", SOON, None, "")
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM chat_actions")).scalar() == 5


def test_history_tool_sends_no_todo_notes(client: TestClient) -> None:
    pid = garden(client)
    assert "notiz" not in json.dumps(call(gt.verlauf, pid))
