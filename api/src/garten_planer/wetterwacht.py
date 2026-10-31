"""wetterwacht (M6b, F-WX-4, N-17): every 10 min the next 48 h of the forecast from
InfluxDB through the alert rules (alerts.py) into Postgres: one alert per event,
one urgent to-do per action (with the affected plants), one push, again only when
it gets clearly worse, an all-clear when the forecast clears. The push goes into
the outbox; the worker (the one with internet) sends it.

Own container, backend network only (InfluxDB + Postgres). Also
`python -m garten_planer.wetterwacht sim [name]`: the /weather-sim scenarios
through the rules with an example garden, no database (#006)."""

import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from garten_planer import alerts
from garten_planer.alerts import Action, Event, Hour, PlantInfo
from garten_planer.config import Config
from garten_planer.influx import Influx, InfluxError, from_config
from garten_planer.routes.todos import TZ, materialize
from garten_planer.schema import plants, push_subs, species, standorte, tasks, todos, weather_alerts
from garten_planer.worker import _settings, enqueue

log = logging.getLogger("garten_planer.wetterwacht")
LOOP_S = 600  # N-17: within 15 min of the forecast showing the event
ALIVE = Path("/tmp/wetterwacht-alive")  # noqa: S108 - heartbeat for the healthcheck, tmpfs
FRESH = timedelta(hours=8)  # a source older than this is not used for alerts
SCENARIOS: dict[str, dict[str, Any]] = json.loads((Path(__file__).parent / "weather_sim.json").read_text("utf-8"))
CATEGORY = {"frost": "winterschutz", "strong_frost": "winterschutz", "late_frost": "winterschutz"}


def scenario_hours(sc: dict[str, Any]) -> list[Hour]:
    start = datetime.fromisoformat(sc["now"])
    temps: list[float] = sc["temps"]
    ground: list[float] = sc.get("ground", temps)
    gust: list[float] = sc.get("gust", [20.0] * len(temps))
    return [Hour(start + timedelta(hours=i), t, ground[i], gust[i]) for i, t in enumerate(temps)]


# ----- forecast from InfluxDB --------------------------------------------------------------


def pick_source(rows: list[dict[str, Any]], now: datetime) -> list[Hour]:
    """DWD when it is fresh, otherwise Open-Meteo when that is fresh, otherwise nothing."""
    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_source.setdefault(str(r.get("source")), []).append(r)
    for source in ("dwd", "openmeteo"):
        got = by_source.get(source, [])
        fetched = max((float(r["fetched"]) for r in got if r.get("fetched") is not None), default=None)
        if got and fetched is not None and now - datetime.fromtimestamp(fetched, UTC) < FRESH:
            return [
                Hour(_utc(r["time"]), _num(r.get("t_air")), _num(r.get("t_ground")), _num(r.get("gust"))) for r in got
            ]
    return []


def _utc(v: Any) -> datetime:
    t = datetime.fromisoformat(str(v))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


async def load_forecast(db: Influx, now: datetime) -> list[Hour]:
    start = (now - timedelta(hours=1)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    rows = await db.query(
        f"SELECT * FROM weather_fc WHERE time >= '{start}' "  # noqa: S608 - own datetime only
        f"AND time < TIMESTAMP '{start}' + INTERVAL '50 hours' ORDER BY time"
    )
    return pick_source(rows, now)


# ----- Postgres --------------------------------------------------------------------------------


async def _plants(c: AsyncConnection) -> list[PlantInfo]:
    rows = await c.execute(
        select(plants.c.id, plants.c.nickname, plants.c.in_container, species.c.german, species.c.latin,
               species.c.growth, standorte.c.type)
        .join(species, species.c.id == plants.c.species_id)
        .join(standorte, standorte.c.id == plants.c.standort_id)
        .where(plants.c.archived_at.is_(None))
        .order_by(species.c.german)
    )  # fmt: skip
    return [PlantInfo(r.id, r.nickname or r.german[0], r.in_container, r.growth, r.type, r.latin) for r in rows]


def _when(e: Event) -> str:
    day = e.day
    names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    night = "in der Nacht auf " if e.kind in alerts.FROST_KINDS else "am "
    return f"{night}{names[day.weekday()]}, {day.day}.{day.month}."


def _title(e: Event, a: Action) -> str:
    return f"{alerts.LABELS[e.kind]} ({alerts.fmt(e.kind, e.value)}): {a.title}"[:120]


def _task_values(e: Event, a: Action, today: date) -> dict[str, Any]:
    """What an alert task says now: value, plants and due date follow the forecast."""
    return {
        "plant_id": a.plant_ids[0] if len(a.plant_ids) == 1 else None,
        "title": _title(e, a),
        "category": CATEGORY.get(e.kind, "sonstiges"),
        "instructions": f"{alerts.LABELS[e.kind]} {_when(e)}: {alerts.fmt(e.kind, e.value)}.\n{a.instructions}",
        "due_date": alerts.due(e, today),
    }


async def _sync_tasks(
    c: AsyncConnection, alert_id: str, e: Event, acts: list[Action], today: date, restart: bool
) -> list[str]:
    """One task per action: new ones inserted, existing ones updated (value, plants, due date).
    `restart` (alert back after it ended) enables them again with a new generation, so a
    fresh to-do appears even when the earlier one was done or skipped. Returns the task ids
    that need occurrences."""
    stamp = datetime.now(UTC)
    ids = []
    for a in acts:
        values = _task_values(e, a, today)
        row = (
            await c.execute(
                select(tasks.c.id, tasks.c.generation).where(
                    tasks.c.alert_id == alert_id, tasks.c.alert_action == a.key
                )
            )
        ).first()
        if row is None:
            tid = uuid.uuid4().hex
            await c.execute(
                tasks.insert().values(
                    id=tid, cut_type=None, recurrence="once", urgent=True, source="alert", alert_id=alert_id,
                    alert_action=a.key, why="Wetterwarnung", enabled=True, generation=1, created_at=stamp,
                    updated_at=stamp, **values,
                )
            )  # fmt: skip
            ids.append(tid)
            continue
        extra: dict[str, Any] = {"enabled": True, "retired": False, "generation": row.generation + 1} if restart else {}
        await c.execute(update(tasks).where(tasks.c.id == row.id).values(updated_at=stamp, **values, **extra))
        ids.append(row.id)
    gone = list(
        (
            await c.execute(
                select(tasks.c.id).where(
                    tasks.c.alert_id == alert_id, tasks.c.alert_action.not_in([a.key for a in acts]), tasks.c.enabled
                )
            )
        ).scalars()
    )
    if gone:  # an action the event no longer needs (e.g. strong frost became frost): out of the lists
        await c.execute(delete(todos).where(todos.c.task_id.in_(gone), todos.c.status == "open"))
        await c.execute(update(tasks).where(tasks.c.id.in_(gone)).values(enabled=False, retired=True, updated_at=stamp))
    return ids


async def _push(c: AsyncConnection, on: bool, title: str, body: str) -> bool:
    """True when a push went into the outbox (switched on and at least one device)."""
    if not on:
        return False
    subs = list((await c.execute(select(push_subs.c.id))).scalars())
    if subs:
        await enqueue(c, subs, title, body)
    return bool(subs)


def _push_text(e: Event, acts: list[Action], again: bool) -> tuple[str, str]:
    head = f"{alerts.LABELS[e.kind]}{' - jetzt stärker' if again else ''}: {alerts.fmt(e.kind, e.value)}"
    todo = "; ".join(a.title for a in acts) or "Keine Pflanze betroffen."
    return head, f"{_when(e)[0].upper()}{_when(e)[1:]}. {todo}"


async def _end(c: AsyncConnection, alert_id: str, status: str) -> None:
    """cancelled (before it started): open to-dos go. past (after its window): open to-dos are
    marked skipped, so the history shows the warning. Tasks leave the lists either way."""
    stamp = datetime.now(UTC)
    ids = list((await c.execute(select(tasks.c.id).where(tasks.c.alert_id == alert_id))).scalars())
    if ids:
        open_ = (todos.c.task_id.in_(ids), todos.c.status == "open")
        if status == "past":
            await c.execute(update(todos).where(*open_).values(status="skipped", done_at=stamp, note="Warnung vorbei"))
        else:
            await c.execute(delete(todos).where(*open_))
        await c.execute(update(tasks).where(tasks.c.id.in_(ids)).values(enabled=False, retired=True, updated_at=stamp))
    await c.execute(
        update(weather_alerts).where(weather_alerts.c.id == alert_id).values(status=status, updated_at=stamp)
    )


async def run_once(engine: AsyncEngine, forecast: list[Hour], now: datetime) -> dict[str, int]:
    """One round. Lifecycle of an alert (one per family and day):
    new -> active (tasks, push); worse -> push again; kind may change inside the frost family;
    before its window starts and clearly better -> cancelled (all-clear push, unless the same
    event just moved to a neighbouring day); after its window -> past (no push)."""
    today = now.astimezone(TZ).date()
    counts = {"created": 0, "worse": 0, "cancelled": 0, "past": 0}
    events = alerts.detect(forecast, now)
    days, nights = alerts.daily(forecast, now), alerts.daily(forecast, now, night=True)
    async with engine.begin() as c:
        push_on = (await _settings(c)).notifications.weather_push
        garden = await _plants(c)
        need: list[str] = []
        seen: set[str] = set()
        for e in events:
            acts = alerts.actions(e.kind, garden)
            fam = alerts.family(e.kind)
            row = (
                await c.execute(
                    select(weather_alerts).where(weather_alerts.c.family == fam, weather_alerts.c.day == e.day)
                )
            ).first()
            stamp = datetime.now(UTC)
            values = {"kind": e.kind, "value": e.value, "first_at": e.first, "status": "active", "updated_at": stamp}
            if row is None or row.status != "active":
                aid = row.id if row is not None else uuid.uuid4().hex
                if row is None:
                    await c.execute(
                        weather_alerts.insert().values(id=aid, family=fam, day=e.day, created_at=stamp, **values)
                    )
                else:  # back after an all-clear
                    await c.execute(update(weather_alerts).where(weather_alerts.c.id == aid).values(**values))
                need += await _sync_tasks(c, aid, e, acts, today, restart=row is not None)
                if await _push(c, push_on, *_push_text(e, acts, again=False)):
                    await c.execute(
                        update(weather_alerts).where(weather_alerts.c.id == aid).values(pushed_value=e.value)
                    )
                counts["created"] += 1
            else:
                aid = row.id
                announced = row.pushed_value if row.pushed_value is not None else row.value
                await c.execute(update(weather_alerts).where(weather_alerts.c.id == aid).values(**values))
                need += await _sync_tasks(c, aid, e, acts, today, restart=False)
                if alerts.worse(e.kind, e.value, announced):
                    if await _push(c, push_on, *_push_text(e, acts, again=True)):
                        await c.execute(
                            update(weather_alerts).where(weather_alerts.c.id == aid).values(pushed_value=e.value)
                        )
                    counts["worse"] += 1
            seen.add(aid)
        event_days = {(alerts.family(e.kind), e.day) for e in events}
        active = (await c.execute(select(weather_alerts).where(weather_alerts.c.status == "active"))).all()
        for old in active:
            if old.id in seen:
                continue
            if now >= alerts.window(old.kind, old.day)[1]:
                await _end(c, old.id, "past")
                counts["past"] += 1
                continue
            stats = (nights if old.family == "frost" else days).get(old.day)
            if not alerts.all_clear(old.kind, old.day, stats, now):
                continue  # still ahead but not clearly better, or already running: keep it
            await _end(c, old.id, "cancelled")
            moved = any((old.family, old.day + timedelta(days=d)) in event_days for d in (-1, 1))
            if old.pushed_value is not None and not moved:
                await _push(c, push_on, f"Entwarnung: {alerts.LABELS[old.kind]}",
                            f"Für {old.day.day}.{old.day.month}. nicht mehr vorhergesagt.")  # fmt: skip
            counts["cancelled"] += 1
        if need:
            await materialize(c, today, need)
    return counts


async def active_alerts(c: AsyncConnection, today: date) -> list[dict[str, Any]]:
    rows = await c.execute(
        select(weather_alerts, func.count(tasks.c.id).label("tasks"))
        .outerjoin(tasks, (tasks.c.alert_id == weather_alerts.c.id) & tasks.c.enabled)
        .where(weather_alerts.c.status == "active", weather_alerts.c.day >= today - timedelta(days=1))
        .group_by(weather_alerts.c.id)
        .order_by(weather_alerts.c.day)
    )
    return [
        {"kind": r.kind, "label": alerts.LABELS[r.kind], "day": r.day.isoformat(), "value": r.value,
         "text": alerts.fmt(r.kind, r.value), "tasks": r.tasks}
        for r in rows
    ]  # fmt: skip


# ----- process ---------------------------------------------------------------------------------


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = Config()
    db = from_config(cfg)
    engine = create_async_engine(cfg.database_url.get_secret_value(), pool_pre_ping=True)
    if db is None:
        log.warning("no GP_INFLUX_TOKEN: weather alerts disabled")
    log.info("wetterwacht started")
    while True:
        alive = db is None
        if db is not None:
            try:
                now = datetime.now(TZ)
                fc = await load_forecast(db, now)
                if not fc:
                    log.warning("no fresh forecast: no new alerts this round")
                counts = await run_once(engine, fc, now)
                if any(counts.values()):
                    log.info("alerts: %s", counts)
                alive = True
            except (httpx.HTTPError, InfluxError) as e:  # InfluxDB away: degraded, not broken
                log.warning("forecast unavailable: %s", type(e).__name__)
                alive = True
            except Exception as e:  # a broken round must show in the healthcheck
                log.warning("round failed: %s", type(e).__name__)
        if alive:
            await asyncio.to_thread(ALIVE.touch)
        await asyncio.sleep(LOOP_S)


def sim(name: str | None) -> int:
    garden = [
        PlantInfo("1", "Zitrone (Kübel)", True, "kuebel", "kuebelplatz", "Citrus limon"),
        PlantInfo("2", "Tomate", False, "gemuese", "gewaechshaus", "Solanum lycopersicum"),
        PlantInfo("3", "Apfel", False, "baum", "beet", "Malus domestica"),
        PlantInfo("4", "Hainbuchenhecke", False, "hecke", "hecke", "Carpinus betulus"),
    ]
    names = [name] if name else sorted(SCENARIOS)
    ok = True
    for n in names:
        sc = SCENARIOS[n]
        now = datetime.fromisoformat(sc["now"])
        events = alerts.detect(scenario_hours(sc), now)
        good = sorted(e.kind for e in events) == sorted(sc["expect"])
        ok &= good
        print(f"{'ok  ' if good else 'FAIL'} {n}: {sc['about']}")
        for e in events:
            when = f"{alerts.fmt(e.kind, e.value)} {_when(e)}, fällig {alerts.due(e, now.date())}"
            print(f"     {alerts.LABELS[e.kind]} {when}")
            for a in alerts.actions(e.kind, garden):
                k = len(a.plant_ids)
                print(f"       - {a.title}" + (f" ({k} Pflanze{'n' if k > 1 else ''})" if k else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["sim"]:
        sys.exit(sim(sys.argv[2] if len(sys.argv) > 2 else None))
    asyncio.run(main())
