"""Garden chat flow (M8): questions queue an answer, the worker streams it in (fake CLI
events here), the history goes into the next prompt, proposals need the user's "Ja"."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from blattwerk.chat import parse_event
from blattwerk.claude_cli import ClaudeError
from blattwerk.worker import TURN, run_chat_jobs
from tests.conftest import BASE, DATABASE_URL

H = {"Origin": BASE}


def delta(t: str) -> dict[str, Any]:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}},
    }


RESULT = {"type": "result", "is_error": False, "total_cost_usd": 0.02, "modelUsage": {"claude-test": {}}}


def fake(events: list[dict[str, Any]] | Exception, seen: list[str] | None = None, before_fail: int = 0) -> Any:
    async def stream(prompt: str, system: str, message_id: str, images: list[bytes]) -> AsyncGenerator[dict[str, Any]]:
        if seen is not None:
            seen.append(prompt)
        if isinstance(events, Exception):
            for i in range(before_fail):
                yield delta(f"Teil{i} ")
            raise events
        for e in events:
            yield e

    return stream


def work(stream: Any, limit: int = 150) -> int:
    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_chat_jobs(engine, stream, daily_limit=limit)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def ask(client: TestClient, q: str, chat_id: str | None = None) -> dict[str, Any]:
    url = f"/api/chats/{chat_id}/messages" if chat_id else "/api/chats"
    r = client.post(url, json={"text": q}, headers=H)
    assert r.status_code in (201, 202), r.text
    return dict(r.json())


def test_events_are_parsed() -> None:
    assert parse_event(delta("Hallo")) == ("text", "Hallo")
    assert parse_event({"type": "stream_event", "event": {"type": "message_start"}}) == ("turn", "")
    assert parse_event(RESULT) == ("result", RESULT)
    assert parse_event({"type": "system", "subtype": "init"}) is None


def test_answer_streams_into_the_message_and_history_goes_along(client: TestClient) -> None:
    first = ask(client, "Wann schneide ich meine Hainbuchenhecke?")
    seen: list[str] = []
    assert work(fake([delta("Im "), delta("Juni."), RESULT], seen)) == 1
    chat = client.get(f"/api/chats/{first['chat_id']}").json()
    assert [(m["role"], m["text"], m["status"]) for m in chat["messages"]] == [
        ("user", "Wann schneide ich meine Hainbuchenhecke?", "done"), ("assistant", "Im Juni.", "done")]  # fmt: skip
    ask(client, "Und wie stark?", first["chat_id"])
    work(fake([delta("Nur leicht."), RESULT], seen))
    assert "Hainbuchenhecke" in seen[1] and "Im Juni." in seen[1] and "Und wie stark?" in seen[1]
    assert client.get("/api/chats").json()[0]["title"].startswith("Wann schneide")


def test_one_question_at_a_time(client: TestClient) -> None:
    first = ask(client, "Frage eins")
    r = client.post(f"/api/chats/{first['chat_id']}/messages", json={"text": "Frage zwei"}, headers=H)
    assert r.status_code == 409


def test_failure_keeps_the_partial_text_and_says_why(client: TestClient) -> None:
    first = ask(client, "Frage")
    work(fake(ClaudeError("Die KI hat nach 300 s nicht geantwortet."), before_fail=2))
    m = client.get(f"/api/chats/{first['chat_id']}").json()["messages"][1]
    assert m["status"] == "failed" and "300 s" in m["error"] and m["text"].startswith("Teil0")


def test_stream_endpoint_sends_the_finished_answer(client: TestClient) -> None:
    first = ask(client, "Frage")
    work(fake([delta("Fertig."), RESULT]))
    with client.stream("GET", f"/api/chats/{first['chat_id']}/stream", params={"message_id": first["message_id"]}) as r:
        body = "".join(r.iter_text())
    assert "Fertig." in body and "event: done" in body


def proposal(db: Engine, kind: str, payload: str) -> str:
    with db.begin() as c:
        c.execute(text("INSERT INTO chats (id, title, created_at, updated_at) VALUES ('c1', 't', now(), now())"))
        c.execute(text("INSERT INTO chat_messages (id, chat_id, role, text, status, created_at) "
                       "VALUES ('m1', 'c1', 'assistant', 'x', 'done', now())"))  # fmt: skip
        c.execute(text("INSERT INTO chat_actions (id, message_id, kind, payload, status, created_at) "
                       "VALUES ('a1', 'm1', :k, CAST(:p AS jsonb), 'proposed', now())"),
                  {"k": kind, "p": payload})  # fmt: skip
    return "a1"


def test_confirmed_task_proposal_becomes_a_task(client: TestClient, db: Engine) -> None:
    soon = (date.today() + timedelta(days=5)).isoformat()
    aid = proposal(db, "aufgabe", '{"title": "Kübel reinholen", "category": "winterschutz", "recurrence": "once", '
                                  f'"due_date": "{soon}", "instructions": "", "urgent": false}}')  # fmt: skip
    r = client.post(f"/api/chat-actions/{aid}/confirm", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "done"
    tasks = client.get("/api/tasks").json()
    assert [(t["title"], t["source"]) for t in tasks] == [("Kübel reinholen", "chat")]
    assert client.post(f"/api/chat-actions/{aid}/confirm", headers=H).status_code == 409  # only once


def test_note_proposal_appends_to_the_plant_and_reject_does_nothing(client: TestClient, db: Engine) -> None:
    st = client.post("/api/standorte", json={"name": "Beet", "light": "sonnig", "type": "beet"}, headers=H).json()
    pid = client.post("/api/plants", json={"species_id": "malus-domestica", "standort_id": st["id"], "notes": "Alt."},
                      headers=H).json()["id"]  # fmt: skip
    aid = proposal(db, "notiz", f'{{"plant_id": "{pid}", "text": "Trägt gut."}}')
    assert client.post(f"/api/chat-actions/{aid}/confirm", headers=H).status_code == 200
    notes = client.get(f"/api/plants/{pid}").json()["notes"]
    assert notes.startswith("Alt.") and notes.endswith("Trägt gut.")


def test_daily_limit(client: TestClient, db: Engine) -> None:
    ask(client, "Frage")
    with db.begin() as c:
        c.execute(text("UPDATE chat_messages SET started_at = now(), status = 'done' WHERE role = 'assistant'"))
    r = client.post("/api/chats", json={"text": "noch eine"}, headers=H)
    assert r.status_code == 201  # limit 150: fine
    with db.begin() as c:
        for i in range(150):
            c.execute(text("INSERT INTO chat_messages (id, chat_id, role, text, status, created_at, started_at) "
                           "SELECT :i, id, 'assistant', '', 'done', now(), now() FROM chats LIMIT 1"),
                      {"i": f"x{i}"})  # fmt: skip
    assert client.post("/api/chats", json={"text": "zu viel"}, headers=H).status_code == 429


def test_an_answer_nobody_started_expires_and_frees_the_chat(client: TestClient, db: Engine) -> None:
    first = ask(client, "Frage")
    with db.begin() as c:
        c.execute(text("UPDATE chat_messages SET created_at = now() - interval '10 minutes'"))
    r = client.post(f"/api/chats/{first['chat_id']}/messages", json={"text": "Noch da?"}, headers=H)
    assert r.status_code == 202


def test_confirm_checks_again_archived_plant_and_expiry(client: TestClient, db: Engine) -> None:
    st = client.post("/api/standorte", json={"name": "Beet", "light": "sonnig", "type": "beet"}, headers=H).json()
    pid = client.post("/api/plants", json={"species_id": "malus-domestica", "standort_id": st["id"]}, headers=H).json()[
        "id"
    ]
    aid = proposal(db, "notiz", f'{{"plant_id": "{pid}", "text": "x"}}')
    client.post(f"/api/plants/{pid}/archive", headers=H)
    assert client.post(f"/api/chat-actions/{aid}/confirm", headers=H).status_code == 409
    with db.begin() as c:
        c.execute(text("UPDATE chat_actions SET created_at = now() - interval '8 days'"))
    assert client.post(f"/api/chat-actions/{aid}/confirm", headers=H).status_code == 409


def test_old_task_proposal_with_a_past_date_is_refused(client: TestClient, db: Engine) -> None:
    aid = proposal(db, "aufgabe", '{"title": "Kübel reinholen", "category": "winterschutz", "recurrence": "once", '
                                  '"due_date": "2020-11-03", "instructions": "", "urgent": false}')  # fmt: skip
    assert client.post(f"/api/chat-actions/{aid}/confirm", headers=H).status_code == 409


def test_short_narration_goes_the_answer_stays(client: TestClient) -> None:
    first = ask(client, "Frage")
    turn = {"type": "stream_event", "event": {"type": "message_start"}}
    long_answer = "Die Hecke im Juni in Form schneiden, " * 5
    events = [turn, delta("Ich schaue nach."), turn, delta(long_answer), turn, delta("Vorschlag steht bereit."), RESULT]
    work(fake(events))
    text_ = client.get(f"/api/chats/{first['chat_id']}").json()["messages"][1]["text"]
    assert text_ == f"{long_answer.strip()}\n\nVorschlag steht bereit."
    assert TURN not in text_


def test_stream_ends_with_timeout_when_no_answer_comes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from blattwerk.routes import chat as chat_routes

    monkeypatch.setattr(chat_routes, "STREAM_MAX_S", 0.5)
    monkeypatch.setattr(chat_routes, "STREAM_POLL_S", 0.1)
    first = ask(client, "Frage")
    with client.stream("GET", f"/api/chats/{first['chat_id']}/stream", params={"message_id": first["message_id"]}) as r:
        body = "".join(r.iter_text())
    assert '"status": "timeout"' in body


def test_a_chat_answer_without_claude_fails_clearly_and_does_not_count(client: TestClient, db: Engine) -> None:
    from blattwerk.claude_cli import NotReady

    first = ask(client, "Frage")
    work(fake(NotReady("Der Garten-Chat ist noch nicht eingerichtet (BW_MCP_DB_PASSWORD fehlt).")))
    m = client.get(f"/api/chats/{first['chat_id']}").json()["messages"][1]
    assert m["status"] == "failed" and "noch nicht eingerichtet" in m["error"]
    with db.connect() as c:
        assert c.execute(text("SELECT started_at FROM chat_messages WHERE role = 'assistant'")).scalar() is None
