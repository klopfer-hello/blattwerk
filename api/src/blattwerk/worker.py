"""Background jobs in their own container, the only one with internet access:
- run_digest: at the time set in Einstellungen, one push listing the due to-dos
  that were not in a digest before (each to-do at most once; nothing new, no push);
- send_pending: delivers the outbox (push_messages) written by the api and the
  digest; drops subscriptions the push service reports gone (404/410), retries
  other failures up to MAX_ATTEMPTS.
`python -m blattwerk.worker` runs both every LOOP_S seconds and touches
ALIVE for the container healthcheck. Logs carry error types only (no endpoints,
no SQL parameters)."""

import asyncio
import contextlib
import json
import logging
import sys
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from blattwerk import chat, mosmix, names, pheno_fetch
from blattwerk.claude_cli import (
    ClaudeError,
    NotReady,
    binary_path,
    config_from_env,
    ensure_cli,
    run_json,
    run_stream,
)
from blattwerk.config import Config
from blattwerk.digest import digest_due, digest_text
from blattwerk.influx import from_config
from blattwerk.jobs import CHAT_QUEUED_FOR, CHAT_STALE, NAME_QUEUED_FOR, fail_stale, used_today
from blattwerk.models import GardenSettings, known_fields
from blattwerk.plan import (
    SCHEMA,
    PlanFacts,
    apply_plan,
    build_prompt,
    sanitize,
    system_for,
)
from blattwerk.routes.photos import purge_photos
from blattwerk.routes.todos import TZ, _active, _plant_join, materialize
from blattwerk.schema import (
    chat_messages,
    chats,
    cultivars,
    kv,
    name_jobs,
    photos,
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

FORECAST_S = 3600  # MOSMIX_L is issued every 6 h; hourly keeps the newest
SEASON_S = 24 * 3600
SEASON_RETRY_S = 3600
FORECAST_RETRY_S = 300  # influxdb still starting, DWD briefly down
CHAT_LOOP_S = 1  # someone is waiting for the answer
PLAN_LOOP_S = 5  # the user waits for the plan; a cheap indexed query
LOOP_S = 30
MAX_ATTEMPTS = 5
NAME_JOBS_KEEP = timedelta(days=30)
AUTH_FAILURES_MAX = 3  # 401/403 in 3 periods: the subscription belongs to old keys (ticket 021)
AUTH_WINDOW = timedelta(hours=6)  # one counted refusal per period: a brief outage is not a dead device
BATCH = 20  # messages per run; ALIVE is touched after each one
NEW_DAYS = 14  # only to-dos due in the last NEW_DAYS count as "new" (no backlog flood for a first device)
KEEP_DAYS = 30  # sent and given-up outbox entries are deleted after this
ALIVE = Path("/tmp/worker-alive")  # noqa: S108 - /tmp is the container's private tmpfs
AI_ALIVE = "/tmp/ai-alive-{}"  # noqa: S108 - one heartbeat per AI loop (plan, name, chat), ticket 027


def beat(name: str) -> None:
    Path(AI_ALIVE.format(name)).touch()


log = logging.getLogger("blattwerk.worker")

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
        await c.execute(  # typed plant names are not kept longer than needed
            delete(name_jobs).where(name_jobs.c.created_at < datetime.now(UTC) - NAME_JOBS_KEEP,
                                    name_jobs.c.status.in_(("done", "failed")))
        )  # fmt: skip
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
                    update(push_subs)
                    .where(push_subs.c.id == r.sub_id)
                    .values(last_ok_at=datetime.now(UTC), auth_failures=0, auth_failed_at=None)
                )
            elif status in (404, 410):  # the device unsubscribed or the browser was reset
                await c.execute(delete(push_subs).where(push_subs.c.id == r.sub_id))
            elif status in (401, 403):  # subscribed with other server keys? counted once per AUTH_WINDOW
                now = datetime.now(UTC)
                fails = (
                    await c.execute(
                        update(push_subs)
                        .where(push_subs.c.id == r.sub_id,
                               push_subs.c.auth_failed_at.is_(None) | (push_subs.c.auth_failed_at < now - AUTH_WINDOW))
                        .values(auth_failures=push_subs.c.auth_failures + 1, auth_failed_at=now)
                        .returning(push_subs.c.auth_failures)
                    )
                ).scalar()  # fmt: skip
                if fails is not None and fails >= AUTH_FAILURES_MAX:
                    await c.execute(delete(push_subs).where(push_subs.c.id == r.sub_id))
                else:
                    await c.execute(
                        update(push_messages)
                        .where(push_messages.c.id == r.id)
                        .values(attempts=push_messages.c.attempts + 1, last_error=f"HTTP {status}")
                    )
            else:
                await c.execute(
                    update(push_messages)
                    .where(push_messages.c.id == r.id)
                    .values(attempts=push_messages.c.attempts + 1, last_error=error or f"HTTP {status}")
                )
                if status:  # the push service answered otherwise: the key was not the problem
                    await c.execute(update(push_subs).where(push_subs.c.id == r.sub_id).values(auth_failures=0))
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
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry URLs (station id)
    cfg = Config()
    engine = create_async_engine(cfg.database_url.get_secret_value(), pool_pre_ping=True)
    sender = make_sender(cfg) if cfg.vapid_private.get_secret_value() else None
    if sender is None:  # nothing could be delivered: do not consume the to-dos either
        log.warning("no BW_VAPID_PRIVATE: push disabled")
    plans = asyncio.create_task(ai_loops(engine, cfg))  # own loops: a plan takes minutes
    forecast = asyncio.create_task(forecast_loop(cfg))
    seasons = asyncio.create_task(season_loop(engine, cfg))
    log.info("worker started")
    while True:
        if plans.done():  # a crash there must not go unnoticed: stop, the restart policy brings us back
            raise RuntimeError("AI loops stopped")
        if forecast.done() and forecast.exception() is not None:
            raise RuntimeError("forecast loop stopped")
        if seasons.done() and seasons.exception() is not None:
            raise RuntimeError("season loop stopped")
        try:
            if sender is not None and (count := await run_digest(engine, datetime.now(TZ))):
                log.info("digest with %d to-dos queued", count)
            if sender is not None and (sent := await send_pending(engine, sender)):
                log.info("%d push messages sent", sent)
            await purge_photos(engine)
        except Exception as e:  # keep running; type only (messages may contain SQL parameters)
            log.warning("job failed: %s", type(e).__name__)
        await asyncio.to_thread(ALIVE.touch)
        await asyncio.sleep(LOOP_S)


# ----- care plans (M5) --------------------------------------------------------------

Runner = Callable[..., Awaitable[tuple[dict[str, Any], dict[str, Any]]]]  # (prompt, system, schema[, images=])


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
                standorte.c.windows,
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
        window=r.window_dir or ", ".join(r.windows) or "keins",  # the nearest one, else all of the room
        window_distance=r.window_distance,
        pot_cm=r.pot_cm,
        pot_material=r.pot_material,
        height_cm=r.height_cm,
    )


def _uncounted(e: Exception) -> dict[str, Any]:
    """A job that never reached Claude does not use up the day's limit (started_at counts)."""
    return {"started_at": None} if isinstance(e, NotReady) else {}


async def run_plan_jobs(engine: AsyncEngine, runner: Runner, daily_limit: int) -> int:
    """Run queued plan jobs one after another; returns how many finished (done or failed).
    Claim and finish are separate short transactions (the CLI takes minutes, no connection is
    held meanwhile); a job lost in between is ended by fail_stale."""
    finished = 0
    while True:
        await asyncio.to_thread(beat, "plan")  # between jobs too: a hung run stops it
        async with engine.begin() as c:
            await fail_stale(c, plan_jobs)
            if await used_today(c, plan_jobs, TZ) >= daily_limit:
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
            raw, info = await runner(build_prompt(facts), system_for(facts), SCHEMA)
            plan = sanitize(raw, indoor=facts.indoor)
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
                    .values(status="failed", error=error, finished_at=datetime.now(UTC), **_uncounted(e))
                )
        finished += 1


async def _photo_bytes(engine: AsyncEngine, ids: list[str]) -> list[bytes]:
    if not ids:
        return []
    async with engine.connect() as c:
        got = {r.id: bytes(r.data) for r in await c.execute(select(photos.c.id, photos.c.data)
                                                              .where(photos.c.id.in_(ids)))}  # fmt: skip
    return [got[i] for i in ids if i in got]


async def run_name_jobs(engine: AsyncEngine, runner: Runner, daily_limit: int) -> int:
    """Run queued name lookups; returns how many finished. Same claim/finish pattern as plans."""
    finished = 0
    while True:
        await asyncio.to_thread(beat, "name")  # between jobs too: a hung run stops it
        async with engine.begin() as c:
            await fail_stale(c, name_jobs, queued_for=NAME_QUEUED_FOR)
            if await used_today(c, name_jobs, TZ) >= daily_limit:
                return finished
            job = (
                await c.execute(
                    select(name_jobs.c.id, name_jobs.c.query, name_jobs.c.photo_ids)
                    .where(name_jobs.c.status == "queued")
                    .order_by(name_jobs.c.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if job is None:
                return finished
            await c.execute(
                update(name_jobs).where(name_jobs.c.id == job.id).values(status="running", started_at=datetime.now(UTC))
            )
        values: dict[str, Any]
        try:
            images = await _photo_bytes(engine, job.photo_ids)
            if len(images) != len(job.photo_ids):
                raise NotReady("Das Foto ist nicht mehr da. Bitte neu aufnehmen.")
            prompt = names.build_prompt(job.query, len(images))
            raw, info = await (runner(prompt, names.SYSTEM, names.SCHEMA, images=images) if images
                               else runner(prompt, names.SYSTEM, names.SCHEMA))  # fmt: skip
            found = names.sanitize(raw)
            values = {"status": "done", "candidates": [x.model_dump() for x in found],
                      "model": info.get("model"), "cost_usd": info.get("cost_usd")}  # fmt: skip
        except Exception as e:  # never leave a job "running"; type only in the log
            error = str(e) if isinstance(e, ClaudeError) else "Unerwarteter Fehler bei der Namenssuche."
            values = {"status": "failed", "error": error, **_uncounted(e)}
            log.warning("name lookup failed: %s", type(e).__name__)
        async with engine.begin() as c:
            await c.execute(
                update(name_jobs).where(name_jobs.c.id == job.id).values(finished_at=datetime.now(UTC), **values)
            )
        finished += 1


Streamer = Callable[[str, str, str, list[bytes]], AsyncGenerator[dict[str, Any]]]
TURN = "\n\n\u2063"  # between assistant turns (text before a tool call is narration)
FLUSH_S = 0.3  # how often a growing answer is written (the web polls it)


async def run_chat_jobs(engine: AsyncEngine, stream: Streamer, daily_limit: int) -> int:
    """Answer queued chat questions one after another; returns how many finished."""
    finished = 0
    while True:
        await asyncio.to_thread(beat, "chat")  # between jobs too: a hung run stops it
        async with engine.begin() as c:
            await fail_stale(c, chat_messages, CHAT_STALE, queued_for=CHAT_QUEUED_FOR)
            if await used_today(c, chat_messages, TZ) >= daily_limit:  # started = assistant rows only
                return finished
            job = (
                await c.execute(
                    select(chat_messages.c.id, chat_messages.c.chat_id, chat_messages.c.created_at)
                    .where(chat_messages.c.status == "queued", chat_messages.c.role == "assistant")
                    .order_by(chat_messages.c.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).first()
            if job is None:
                return finished
            await c.execute(
                update(chat_messages)
                .where(chat_messages.c.id == job.id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            earlier = (
                await c.execute(
                    select(chat_messages.c.id, chat_messages.c.role, chat_messages.c.text, chat_messages.c.photos)
                    .where(chat_messages.c.chat_id == job.chat_id, chat_messages.c.created_at < job.created_at,
                           chat_messages.c.status == "done")
                    .order_by(chat_messages.c.created_at)
                )
            ).all()  # fmt: skip
            asked = earlier[-1] if earlier and earlier[-1].role == "user" else None
            # the newest photos in the visible history go along (a text answer to "Blattunterseite?" keeps
            # them); older photos only as "[Foto]" in the text (cost)
            shown = next((r for r in reversed(earlier[-chat.HISTORY - 1 :]) if r.role == "user" and r.photos), None)
            images: list[bytes] = []
            if shown is not None:
                got = {r.id: bytes(r.data) for r in await c.execute(
                    select(photos.c.id, photos.c.data).where(photos.c.id.in_(shown.photos)))}  # fmt: skip
                images = [got[i] for i in shown.photos if i in got]
            about = (
                await c.execute(
                    select(plants.c.id, plants.c.nickname, species.c.german)
                    .join(chats, chats.c.plant_id == plants.c.id)
                    .join(species, species.c.id == plants.c.species_id)
                    .where(chats.c.id == job.chat_id)
                )
            ).first()
        history = [(r.role, r.text + chat.photo_mark(len(r.photos))) for r in earlier]
        question = history.pop()[1] if asked is not None else ""
        plant = None
        if about is not None:
            plant = (about.nickname or (about.german[0] if about.german else "Pflanze"), about.id)
        text, last_flush, values = "", 0.0, {}
        try:
            prompt = chat.build_prompt(history, question, plant)
            async with contextlib.aclosing(stream(prompt, chat.SYSTEM, job.id, images)) as events:
                async for event in events:
                    parsed = chat.parse_event(event)
                    if parsed is None:
                        continue
                    kind, data = parsed
                    if kind == "turn" and text and not text.endswith(TURN):
                        text += TURN  # invisible mark: the stored answer keeps only the last turn
                    elif kind == "text":
                        text += data
                    elif kind == "result":
                        if data.get("is_error"):
                            raise ClaudeError("Die KI hat einen Fehler gemeldet. Bitte später nochmal versuchen.")
                        values = {
                            "cost_usd": data.get("total_cost_usd"),
                            "model": next(iter(data.get("modelUsage") or {}), None),
                        }
                    now = asyncio.get_running_loop().time()
                    if kind == "text" and now - last_flush >= FLUSH_S:
                        last_flush = now
                        async with engine.begin() as c:
                            await c.execute(update(chat_messages).where(chat_messages.c.id == job.id).values(text=text))
            values |= {"status": "done", "text": chat.final_answer(text, TURN) or "(keine Antwort)"}
        except asyncio.CancelledError:  # worker stops: the answer ends now, not after the stale sweep
            async with engine.begin() as c:
                await c.execute(update(chat_messages).where(chat_messages.c.id == job.id).values(
                    status="failed", text=text.replace(TURN, "\n\n").strip(),
                    error="Unterbrochen (Server-Neustart). Bitte nochmal fragen.",
                    finished_at=datetime.now(UTC)))  # fmt: skip
            raise
        except Exception as e:  # keep what came so far; the message says why
            error = str(e) if isinstance(e, ClaudeError) else "Unerwarteter Fehler bei der Antwort."
            values = {"status": "failed", "text": text.replace(TURN, "\n\n").strip(), "error": error, **_uncounted(e)}
            log.warning("chat answer failed: %s", type(e).__name__)
        async with engine.begin() as c:
            await c.execute(
                update(chat_messages)
                .where(chat_messages.c.id == job.id)
                .values(finished_at=datetime.now(UTC), **values)
            )
            await c.execute(update(chats).where(chats.c.id == job.chat_id).values(updated_at=datetime.now(UTC)))
        finished += 1


def mcp_url(cfg: Config) -> str:
    """The app's database URL with the chat tools' own role (read + proposals only, ticket 034)."""
    url = make_url(cfg.database_url.get_secret_value())
    password = cfg.mcp_db_password.get_secret_value()
    if not password:
        raise NotReady("Der Garten-Chat ist noch nicht eingerichtet (BW_MCP_DB_PASSWORD fehlt).")
    return url.set(username="blattwerk_mcp", password=password).render_as_string(hide_password=False)


async def wait_ready(ready: asyncio.Event) -> None:
    await ready.wait()


async def ai_loops(engine: AsyncEngine, cfg: Config) -> None:
    """Install the pinned CLI (retried), then serve both AI queues; a name lookup never waits behind a plan."""
    cli = config_from_env()
    async with engine.begin() as c:  # one worker: anything still "running" lost its run with the last process
        for table in (plan_jobs, name_jobs):
            await fail_stale(c, table, timedelta(0))
    if not (cli.version and cli.sha256):
        log.warning("no BW_CLAUDE_VERSION/BW_CLAUDE_SHA256: AI features disabled")

    def runner(budget: float) -> Runner:
        async def run(
            prompt: str, system: str, schema: dict[str, Any], images: list[bytes] | None = None
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return await run_json(cli, prompt, system, schema, model=cfg.plan_model, budget_usd=budget, images=images)

        return run

    ready = asyncio.Event()  # jobs wait for the CLI instead of failing during the first download

    async def install() -> None:
        while cli.version and cli.sha256 and not binary_path(cli).exists():
            try:
                await asyncio.to_thread(ensure_cli, cli)
                log.info("claude cli %s ready", cli.version)
            except Exception as e:  # retried every 10 min
                log.warning("claude cli install failed: %s", type(e).__name__)
            if not binary_path(cli).exists():
                await asyncio.sleep(600)
        ready.set()  # also without version/sha: jobs then fail with a clear message

    async def serve(name: str, run: Callable[[], Awaitable[int]]) -> None:
        await wait_ready(ready)
        while True:
            try:
                await run()
            except Exception as e:  # keep running; type only
                log.warning("%s jobs failed: %s", name, type(e).__name__)
            await asyncio.sleep(PLAN_LOOP_S)

    def streamer() -> Streamer:
        def run(prompt: str, system: str, message_id: str, images: list[bytes]) -> AsyncGenerator[dict[str, Any]]:
            env = {  # mcp_url raises a German ClaudeError when the role's password is missing: that answer fails
                "BW_DATABASE_URL": mcp_url(cfg),
                "BW_INFLUX_URL": cfg.influx_url,
                "BW_INFLUX_TOKEN": cfg.influx_token.get_secret_value(),
                "PYTHONDONTWRITEBYTECODE": "1",
                "BW_CHAT_MESSAGE_ID": message_id,
            }
            server = {"command": sys.executable, "args": ["-m", "blattwerk.mcp_blattwerk"], "env": env}
            return run_stream(cli, prompt, system, {"blattwerk": server}, "mcp__blattwerk__*", model=cfg.plan_model,
                              budget_usd=cfg.chat_budget_usd, images=images)  # fmt: skip

        return run

    async def serve_fast(name: str, run: Callable[[], Awaitable[int]]) -> None:
        await wait_ready(ready)
        while True:
            try:
                await run()
            except Exception as e:  # keep running; type only
                log.warning("%s jobs failed: %s", name, type(e).__name__)
            await asyncio.sleep(CHAT_LOOP_S)

    await asyncio.gather(
        install(),
        serve_fast("chat", lambda: run_chat_jobs(engine, streamer(), cfg.chat_daily_limit)),
        serve("plan", lambda: run_plan_jobs(engine, runner(cfg.plan_budget_usd), cfg.plan_daily_limit)),
        serve("name", lambda: run_name_jobs(engine, runner(cfg.name_budget_usd), cfg.name_daily_limit)),
    )


async def forecast_loop(cfg: Config) -> None:
    """DWD MOSMIX for the nearest station, hourly (N-16); after a failure again in a few minutes."""
    db = from_config(cfg)
    if db is None or cfg.lat is None or cfg.lon is None:
        log.warning("no BW_INFLUX_TOKEN or BW_LAT/BW_LON: DWD forecast disabled")
        return
    stations: list[mosmix.Station] = []
    while True:
        try:
            stations = stations or await mosmix.stations_near(cfg.lat, cfg.lon)
            station, hours = await mosmix.fetch(db, stations)
            stations = [station, *(s for s in stations if s != station)]  # keep the one that works first
            log.info("dwd forecast: %d hours", hours)  # no station id: it says where the garden is
            await asyncio.sleep(FORECAST_S)
        except Exception as e:  # keep running; type only
            log.warning("dwd forecast failed: %s", type(e).__name__)
            await asyncio.sleep(FORECAST_RETRY_S)


async def season_loop(engine: AsyncEngine, cfg: Config) -> None:
    """Phenology and growing degree days once a day; normals once per region (M7a)."""
    if cfg.lat is None or cfg.lon is None:
        log.warning("no BW_LAT/BW_LON: phenological season from the normal calendar only")
        return
    lat, lon = cfg.lat, cfg.lon
    while True:
        today = datetime.now(TZ).date()
        ok = True
        for name, job in (
            ("phenology", lambda d=today: pheno_fetch.update_current(engine, lat, lon, d)),
            ("growing degree days", lambda d=today: pheno_fetch.update_gdd(engine, lat, lon, d)),
        ):
            try:
                log.info("%s: %s", name, await job())
            except Exception as e:  # keep running; type only
                ok = False
                log.warning("%s failed: %s", name, type(e).__name__)
        try:
            if await pheno_fetch.normals_due(engine, lat, lon, datetime.now(UTC)):
                log.info("phenology normals: %d phases", await pheno_fetch.update_normals(engine, lat, lon))
        except Exception as e:
            ok = False
            log.warning("phenology normals failed: %s", type(e).__name__)
        await asyncio.sleep(SEASON_S if ok else SEASON_RETRY_S)


if __name__ == "__main__":
    asyncio.run(main())
