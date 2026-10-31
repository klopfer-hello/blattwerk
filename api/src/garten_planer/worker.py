"""Background jobs in their own container, the only one with internet access:
- run_digest: at the time set in Einstellungen, one push listing the due to-dos
  that were not in a digest before (each to-do at most once; nothing new, no push);
- send_pending: delivers the outbox (push_messages) written by the api and the
  digest; drops subscriptions the push service reports gone (404/410), retries
  other failures up to MAX_ATTEMPTS.
`python -m garten_planer.worker` runs both every LOOP_S seconds and touches
ALIVE for the container healthcheck. Logs carry error types only (no endpoints,
no SQL parameters)."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from garten_planer.claude_cli import ClaudeError, binary_path, config_from_env, ensure_cli, run_json
from garten_planer.config import Config
from garten_planer.digest import digest_due, digest_text
from garten_planer.models import GardenSettings, known_fields
from garten_planer.plan import (
    SCHEMA,
    SYSTEM,
    PlanFacts,
    apply_plan,
    build_prompt,
    fail_stale,
    sanitize,
    used_today,
)
from garten_planer.routes.todos import TZ, _active, _plant_join, materialize
from garten_planer.schema import (
    cultivars,
    kv,
    plan_jobs,
    plants,
    push_messages,
    push_subs,
    settings,
    species,
    standorte,
    tasks,
    todos,
)

PLAN_LOOP_S = 5  # the user waits for the plan; a cheap indexed query
LOOP_S = 30
MAX_ATTEMPTS = 5
BATCH = 20  # messages per run; ALIVE is touched after each one
NEW_DAYS = 14  # only to-dos due in the last NEW_DAYS count as "new" (no backlog flood for a first device)
KEEP_DAYS = 30  # sent and given-up outbox entries are deleted after this
ALIVE = Path("/tmp/worker-alive")  # noqa: S108 - /tmp is the container's private tmpfs
log = logging.getLogger("garten_planer.worker")

Sender = Callable[[str, dict[str, str], str], Awaitable[int]]


async def _settings(c: AsyncConnection) -> GardenSettings:
    data = (await c.execute(select(settings.c.data).where(settings.c.id == 1))).scalar()
    return GardenSettings.model_validate(known_fields(GardenSettings, data or {}))


async def enqueue(c: AsyncConnection, sub_ids: list[str], title: str, body: str, url: str = "/#/heute") -> None:
    stamp = datetime.now(UTC)
    rows = [
        {
            "id": uuid.uuid4().hex,
            "sub_id": s,
            "title": title,
            "body": body,
            "url": url,
            "created_at": stamp,
            "attempts": 0,
        }
        for s in sub_ids
    ]
    if rows:
        await c.execute(pg_insert(push_messages).values(rows))


async def run_digest(engine: AsyncEngine, at: datetime) -> int:
    """Number of to-dos announced (0: not due, nothing new or no device subscribed)."""
    async with engine.begin() as c:
        subs = list((await c.execute(select(push_subs.c.id))).scalars())
        if not subs:
            return 0
        n = (await _settings(c)).notifications
        last = (await c.execute(select(kv.c.value).where(kv.c.key == "last_digest"))).scalar()
        if not digest_due(
            at, n.digest_mode, n.digest_time, n.digest_weekday, date.fromisoformat(last) if last else None
        ):
            return 0
        await materialize(c, at.date())
        rows = (
            await c.execute(
                select(todos.c.id, tasks.c.title)
                .select_from(_plant_join.join(todos, todos.c.task_id == tasks.c.id))
                .where(
                    todos.c.status == "open",
                    todos.c.due_from <= at.date(),
                    todos.c.due_from > at.date() - timedelta(days=NEW_DAYS),
                    todos.c.notified_at.is_(None),
                    tasks.c.enabled,
                    _active,
                )
                .order_by(tasks.c.title)
            )
        ).all()
        if not rows:
            return 0  # the day is not used up: a to-do added later today still gets announced
        title, body = digest_text([r.title for r in rows])
        await enqueue(c, subs, title, body)
        await c.execute(update(todos).where(todos.c.id.in_([r.id for r in rows])).values(notified_at=datetime.now(UTC)))
        stmt = pg_insert(kv).values(key="last_digest", value=at.date().isoformat())
        await c.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value}))
        return len(rows)


async def send_pending(engine: AsyncEngine, sender: Sender) -> int:
    """Deliver the outbox; returns how many messages were accepted by the push services.
    Also removes sent and given-up entries older than KEEP_DAYS."""
    async with engine.begin() as c:
        old = datetime.now(UTC) - timedelta(days=KEEP_DAYS)
        await c.execute(
            delete(push_messages).where(
                push_messages.c.created_at < old,
                push_messages.c.sent_at.is_not(None) | (push_messages.c.attempts >= MAX_ATTEMPTS),
            )
        )
    async with engine.connect() as c:
        rows = (
            await c.execute(
                select(push_messages, push_subs.c.endpoint, push_subs.c.p256dh, push_subs.c.auth)
                .join(push_subs)
                .where(push_messages.c.sent_at.is_(None), push_messages.c.attempts < MAX_ATTEMPTS)
                .order_by(push_messages.c.created_at)
                .limit(BATCH)
            )
        ).all()
    ok = 0
    for r in rows:
        payload = json.dumps({"title": r.title, "body": r.body, "url": r.url})
        try:
            status, error = await sender(r.endpoint, {"p256dh": r.p256dh, "auth": r.auth}, payload), None
        except Exception as e:  # network trouble etc.: retry later
            status, error = 0, type(e).__name__
        async with engine.begin() as c:
            if 200 <= status < 300:
                ok += 1
                await c.execute(
                    update(push_messages).where(push_messages.c.id == r.id).values(sent_at=datetime.now(UTC))
                )
                await c.execute(
                    update(push_subs).where(push_subs.c.id == r.sub_id).values(last_ok_at=datetime.now(UTC))
                )
            elif status in (404, 410):  # the device unsubscribed or the browser was reset
                await c.execute(delete(push_subs).where(push_subs.c.id == r.sub_id))
            else:
                await c.execute(
                    update(push_messages)
                    .where(push_messages.c.id == r.id)
                    .values(attempts=push_messages.c.attempts + 1, last_error=error or f"HTTP {status}")
                )
        await asyncio.to_thread(ALIVE.touch)  # a slow push service must not look like a dead worker
    return ok


def make_sender(cfg: Config) -> Sender:
    import requests
    from pywebpush import WebPushException, webpush  # only the worker needs it

    private = cfg.vapid_private.get_secret_value()
    session = requests.Session()
    session.max_redirects = 0  # never follow a push service's redirect anywhere else (review M3b)

    async def send(endpoint: str, keys: dict[str, str], payload: str) -> int:
        def go() -> int:
            try:
                r = webpush(
                    {"endpoint": endpoint, "keys": keys},
                    payload,
                    vapid_private_key=private,
                    vapid_claims={"sub": cfg.vapid_subject},
                    ttl=24 * 3600,
                    timeout=10,
                    requests_session=session,
                )
                return int(r.status_code)
            except WebPushException as e:
                return int(e.response.status_code) if e.response is not None else 0

        return await asyncio.to_thread(go)

    return send


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    engine = create_async_engine(cfg.database_url.get_secret_value(), pool_pre_ping=True)
    sender = make_sender(cfg) if cfg.vapid_private.get_secret_value() else None
    if sender is None:  # nothing could be delivered: do not consume the to-dos either
        log.warning("no GP_VAPID_PRIVATE: push disabled")
    plans = asyncio.create_task(plan_loop(engine, cfg))  # own loop: a plan takes minutes
    log.info("worker started")
    while True:
        if plans.done():  # a crash there must not go unnoticed: stop, the restart policy brings us back
            raise RuntimeError("plan loop stopped")
        try:
            if sender is not None and (count := await run_digest(engine, datetime.now(TZ))):
                log.info("digest with %d to-dos queued", count)
            if sender is not None and (sent := await send_pending(engine, sender)):
                log.info("%d push messages sent", sent)
        except Exception as e:  # keep running; type only (messages may contain SQL parameters)
            log.warning("job failed: %s", type(e).__name__)
        await asyncio.to_thread(ALIVE.touch)
        await asyncio.sleep(LOOP_S)


# ----- care plans (M5) --------------------------------------------------------------

Runner = Callable[[str, str, dict[str, Any]], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]


async def _plan_facts(c: AsyncConnection, plant_id: str) -> PlanFacts:
    r = (
        await c.execute(
            select(
                plants,
                species.c.latin,
                species.c.german,
                cultivars.c.name.label("cultivar_name"),
                standorte.c.light,
                standorte.c.type.label("standort_type"),
            )
            .join(species, species.c.id == plants.c.species_id)
            .join(standorte, standorte.c.id == plants.c.standort_id)
            .outerjoin(cultivars, cultivars.c.id == plants.c.cultivar_id)
            .where(plants.c.id == plant_id)
        )
    ).one()
    g = await _settings(c)
    return PlanFacts(
        latin=r.latin,
        german=(r.german or [r.latin])[0],
        cultivar=r.cultivar_name,
        form=r.form,
        rootstock=r.rootstock,
        planted_year=r.planted_year,
        in_container=r.in_container,
        light=r.light,
        standort_type=r.standort_type,
        bundesland=g.location.bundesland,
        fertiliser=g.preferences.fertiliser,
        eco_defaults=g.preferences.eco_defaults,
    )


async def run_plan_jobs(engine: AsyncEngine, runner: Runner, daily_limit: int) -> int:
    """Run queued plan jobs one after another; returns how many finished (done or failed).
    Claim and finish are separate short transactions (the CLI takes minutes, no connection is
    held meanwhile); a job lost in between is ended by fail_stale."""
    finished = 0
    while True:
        async with engine.begin() as c:
            await fail_stale(c)
            if await used_today(c, TZ) >= daily_limit:
                return finished  # the api says so when asked; the rest waits for tomorrow
            job = (
                await c.execute(
                    select(plan_jobs.c.id, plan_jobs.c.plant_id)
                    .where(plan_jobs.c.status == "queued")
                    .order_by(plan_jobs.c.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if job is None:
                return finished
            await c.execute(
                update(plan_jobs).where(plan_jobs.c.id == job.id).values(status="running", started_at=datetime.now(UTC))
            )
        error = "Unerwarteter Fehler beim Erstellen des Plans."
        try:
            async with engine.connect() as c:
                facts = await _plan_facts(c, job.plant_id)
            raw, info = await runner(build_prompt(facts), SYSTEM, SCHEMA)
            plan = sanitize(raw)
            async with engine.begin() as c:  # plan, tasks, to-dos and "done" together or not at all
                plan_id, ids = await apply_plan(c, job.plant_id, plan, info)
                await materialize(c, datetime.now(TZ).date(), ids)
                await c.execute(
                    update(plan_jobs)
                    .where(plan_jobs.c.id == job.id)
                    .values(status="done", plan_id=plan_id, finished_at=datetime.now(UTC))
                )
            log.info("plan done (%d tasks, %d dropped)", len(plan.tasks), plan.dropped)
        except Exception as e:  # never leave a job "running"; type only in the log
            if isinstance(e, ClaudeError):
                error = str(e)
            log.warning("plan failed: %s", type(e).__name__)
            async with engine.begin() as c:
                await c.execute(
                    update(plan_jobs)
                    .where(plan_jobs.c.id == job.id)
                    .values(status="failed", error=error, finished_at=datetime.now(UTC))
                )
        finished += 1


async def plan_loop(engine: AsyncEngine, cfg: Config) -> None:
    """Install the pinned CLI (once per volume), then run queued plan jobs."""
    cli = config_from_env()
    async with engine.begin() as c:  # one worker: anything still "running" lost its run with the last process
        await fail_stale(c, timedelta(0))
    if not (cli.version and cli.sha256):
        log.warning("no GP_CLAUDE_VERSION/GP_CLAUDE_SHA256: care plans disabled")
    next_install = 0.0

    async def runner(prompt: str, system: str, schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return await run_json(cli, prompt, system, schema, model=cfg.plan_model, budget_usd=cfg.plan_budget_usd)

    while True:
        if cli.version and cli.sha256 and not binary_path(cli).exists() and time.monotonic() >= next_install:
            try:  # retried every 10 min after a failed download; jobs meanwhile fail with a clear message
                await asyncio.to_thread(ensure_cli, cli)
                log.info("claude cli %s ready", cli.version)
            except Exception as e:
                log.warning("claude cli install failed: %s", type(e).__name__)
                next_install = time.monotonic() + 600
        try:
            await run_plan_jobs(engine, runner, cfg.plan_daily_limit)
        except Exception as e:  # keep running; type only
            log.warning("plan jobs failed: %s", type(e).__name__)
        await asyncio.sleep(PLAN_LOOP_S)


if __name__ == "__main__":
    asyncio.run(main())
