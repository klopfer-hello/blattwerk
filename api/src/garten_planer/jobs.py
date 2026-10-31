"""Bookkeeping shared by the AI job queues (care plans, name suggestions): the api
queues, the worker claims; a job whose worker died must not block forever, and a
daily limit caps what the household can spend."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

STALE = timedelta(minutes=15)  # a running job older than this lost its worker (CLI timeout is 5 min)
INTERRUPTED = "Unterbrochen (Server-Neustart). Bitte nochmal versuchen."
NAME_QUEUED_FOR = timedelta(minutes=10)
CHAT_QUEUED_FOR = timedelta(minutes=3)  # nobody waits longer for an answer to start
CHAT_STALE = timedelta(minutes=8)  # CLI timeout is 5 min  # a name lookup nobody started by then is dropped
EXPIRED = "Die KI war zu lange beschäftigt. Bitte nochmal versuchen."


async def fail_stale(
    c: AsyncConnection, table: Table, older_than: timedelta = STALE, queued_for: timedelta | None = None
) -> None:
    """Running jobs whose worker died (restart, deploy, OOM) end as failed; with `queued_for`,
    jobs nobody started in that time too (the user has long left the screen)."""
    now = datetime.now(UTC)
    await c.execute(
        update(table)
        .where(table.c.status == "running", table.c.started_at < now - older_than)
        .values(status="failed", error=INTERRUPTED, finished_at=now)
    )
    if queued_for is not None:
        await c.execute(
            update(table)
            .where(table.c.status == "queued", table.c.created_at < now - queued_for)
            .values(status="failed", error=EXPIRED, finished_at=now)
        )


async def used_today(c: AsyncConnection, table: Table, tz: Any, column: str = "started_at") -> int:
    """Jobs today; the api counts created ones (asked), the worker started ones (paid)."""
    midnight = datetime.combine(datetime.now(tz).date(), datetime.min.time(), tz)
    count = select(func.count()).select_from(table).where(table.c[column] >= midnight)
    return int((await c.execute(count)).scalar_one())
