"""The chat tools' own database role (ticket 034): they read the garden and may only add
proposals; a bug in a tool cannot change or delete anything else."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from blattwerk import blattwerk_tools as gt
from blattwerk.migrate import set_mcp_password
from tests.conftest import DATABASE_URL
from tests.test_blattwerk_tools import chat_message, garden

MCP_URL = DATABASE_URL.replace("//test:test@", "//blattwerk_mcp:mcp-test-pw@")


@pytest.fixture
def mcp_db(db: Engine) -> Iterator[Engine]:
    set_mcp_password(DATABASE_URL, "mcp-test-pw")
    engine = create_engine(MCP_URL)
    yield engine
    engine.dispose()


def test_role_reads_the_garden_and_may_only_add_proposals(client: TestClient, db: Engine, mcp_db: Engine) -> None:
    garden(client)
    chat_message(db)
    with mcp_db.begin() as c:
        assert c.execute(text("SELECT count(*) FROM plants")).scalar() == 1
        c.execute(text("INSERT INTO chat_actions (id, message_id, kind, payload, status, created_at) "
                       "VALUES ('a1', 'm1', 'notiz', '{}', 'proposed', now())"))  # fmt: skip
    for forbidden in ("UPDATE plants SET nickname = 'x'", "DELETE FROM tasks", "INSERT INTO tasks (id) VALUES ('x')",
                      "UPDATE chat_actions SET status = 'done'", "DELETE FROM chat_actions",
                      "SELECT * FROM push_subs", "SELECT * FROM chat_messages"):  # fmt: skip
        with pytest.raises(ProgrammingError, match="permission denied"), mcp_db.begin() as c:
            c.execute(text(forbidden))


def test_the_tools_work_under_the_role(client: TestClient, db: Engine, mcp_db: Engine) -> None:
    pid = garden(client)
    chat_message(db)

    async def go() -> list[dict[str, object]]:
        engine = create_async_engine(MCP_URL)
        try:
            async with engine.begin() as c:
                from datetime import date, timedelta

                today = date.today()
                return [
                    await gt.ueberblick(c, today), await gt.pflanze(c, pid, today), await gt.aufgaben(c, today),
                    await gt.jahreszeit(c, today), await gt.verlauf(c, pid),
                    await gt.aufgabe_vorschlagen(c, "m1", "Kübel rein", str(today + timedelta(days=2)), pid, ""),
                ]  # fmt: skip
        finally:
            await engine.dispose()

    results = asyncio.run(go())
    assert all("fehler" not in r for r in results) and results[-1]["vorgeschlagen"] is True
