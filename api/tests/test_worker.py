"""Worker jobs against the real DB: the digest picks only new due to-dos and
sends each at most once; the outbox sender marks sent, drops dead
subscriptions (404/410) and retries other failures."""

import asyncio
from datetime import datetime, time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from garten_planer.routes.todos import TZ, now
from garten_planer.worker import run_digest, send_pending
from tests.conftest import BASE, DATABASE_URL
from tests.test_push import FCM, sub

H = {"Origin": BASE}
SAT_9 = datetime(2026, 11, 7, 9, 0, tzinfo=TZ)


def task(client: TestClient, title: str) -> None:
    body = {"title": title, "category": "schnitt", "recurrence": "yearly", "month_from": 11, "month_to": 11}
    assert client.post("/api/tasks", json=body, headers=H).status_code == 201


def run(coro_fn: Any, *args: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await coro_fn(engine, *args)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def outbox(db: Engine) -> list[tuple[Any, ...]]:
    with db.connect() as c:
        return [
            tuple(r)
            for r in c.execute(text("SELECT title, body, sent_at IS NOT NULL FROM push_messages ORDER BY created_at"))
        ]


def test_digest_sends_new_due_todos_once(client: TestClient, db: Engine) -> None:
    client.app.dependency_overrides[now] = lambda: SAT_9  # type: ignore[attr-defined]
    client.post("/api/push/subscriptions", json=sub(), headers=H)
    task(client, "Hirse binden")
    task(client, "Leimring prüfen")
    assert run(run_digest, SAT_9) == 2
    assert outbox(db) == [("2 neue Aufgaben im Garten", "Hirse binden und Leimring prüfen", False)]
    assert run(run_digest, SAT_9) == 0  # same day: not again
    next_day = datetime.combine(SAT_9.date().replace(day=8), time(9), TZ)
    assert run(run_digest, next_day) == 0  # nothing new: no push
    task(client, "Neue Aufgabe")
    assert run(run_digest, next_day) == 1


def test_digest_without_subscriptions_marks_nothing(client: TestClient, db: Engine) -> None:
    task(client, "Hirse binden")
    assert run(run_digest, SAT_9) == 0
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM todos WHERE notified_at IS NOT NULL")).scalar() == 0


def test_sender_marks_sent_drops_gone_and_retries(client: TestClient, db: Engine) -> None:
    client.post("/api/push/subscriptions", json=sub(), headers=H)
    client.post("/api/push/subscriptions", json=sub(FCM + "-gone"), headers=H)
    client.post("/api/push/subscriptions", json=sub(FCM + "-flaky"), headers=H)
    for e in (FCM, FCM + "-gone", FCM + "-flaky"):
        client.post("/api/push/test", json={"endpoint": e}, headers=H)
    sent: list[str] = []

    async def fake(endpoint: str, keys: dict[str, str], payload: str) -> int:
        sent.append(endpoint)
        return {FCM: 201, FCM + "-gone": 410}.get(endpoint, 503)

    assert run(send_pending, fake) == 1
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM push_subs")).scalar() == 2  # the 410 one is gone
        row = c.execute(text("SELECT attempts, last_error FROM push_messages WHERE sent_at IS NULL")).one()
    assert row == (1, "HTTP 503")
    assert sorted(sent) == sorted([FCM, FCM + "-gone", FCM + "-flaky"])


def test_old_overdue_todos_are_not_announced(client: TestClient) -> None:
    """The first device would otherwise get every to-do ever overdue at once."""
    client.app.dependency_overrides[now] = lambda: SAT_9  # type: ignore[attr-defined]
    client.post("/api/push/subscriptions", json=sub(), headers=H)
    body = {"title": "Uralt", "category": "schnitt", "recurrence": "once", "due_date": "2026-10-01"}
    assert client.post("/api/tasks", json=body, headers=H).status_code == 201
    task(client, "Frisch")
    assert run(run_digest, SAT_9) == 1


def test_old_outbox_entries_are_cleaned_up(client: TestClient, db: Engine) -> None:
    client.post("/api/push/subscriptions", json=sub(), headers=H)
    client.post("/api/push/test", json={"endpoint": FCM}, headers=H)
    with db.begin() as c:
        c.execute(
            text(
                "UPDATE push_messages SET created_at = now() - interval '40 days', sent_at = now() - interval '40 days'"
            )
        )

    async def never(endpoint: str, keys: dict[str, str], payload: str) -> int:
        raise AssertionError("nothing to send")

    run(send_pending, never)
    assert outbox(db) == []
