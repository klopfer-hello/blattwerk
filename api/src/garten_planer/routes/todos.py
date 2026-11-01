"""To-do engine over HTTP (F-TD): tasks (what, when), their occurrences (the
checklist), and the calendar projection.

Rules (simple on purpose, after review M3a):
- Occurrences are created idempotently by `materialize` (UNIQUE task, generation,
  period) whenever a task changes, an occurrence is closed, and when Heute is read.
- Interval tasks: if nothing is open, the next one is due at "last done/skipped +
  n days" (or start_date / today without history). This one rule covers done,
  undo, pause/resume and interval changes. Indoor (M11): a winter n (Nov-Feb), an
  active month window, and the soil feedback after watering changes n.
- Watering only for indoor plants (F-CP-6); the garden rules (§ 39) not for them.
- A timing change starts a new generation: old occurrences stay as history,
  open ones of older generations are removed. History is never deleted.
- Archived plants produce no to-dos (their tasks are skipped, not changed).
- Heute shows the newest open occurrence per task (an overdue one from last
  year is replaced by this year's)."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Row, and_, case, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from garten_planer.catalog import ready
from garten_planer.db import Conn
from garten_planer.errors import ApiError, invalid, not_found
from garten_planer.legal import (
    LegalSettings,
    PlantFacts,
    adjust_window,
    allowed_months,
    blocked_until,
    is_fruit_tree,
    notes,
)
from garten_planer.models import GardenSettings, NoteIn, PostponeIn, SoilIn, Task, TaskIn, known_fields
from garten_planer.schedule import (
    HORIZON_DAYS,
    Occurrence,
    TaskTiming,
    in_season,
    interval_after,
    months_in_year,
    occurrences,
    rhythm_field,
    yearly_span,
)
from garten_planer.schema import (
    INDOOR,
    INDOOR_CATEGORIES,
    cultivars,
    plants,
    settings,
    species,
    standorte,
    tasks,
    todos,
)
from garten_planer.season_dates import safe_phase_starts

router = APIRouter(dependencies=[Depends(ready)])
TZ = ZoneInfo("Europe/Berlin")
TIMING = (
    "recurrence", "due_date", "month_from", "month_to", "interval_days", "winter_interval_days", "start_date",
    "pheno_phase", "pheno_offset", "pheno_window",
)  # fmt: skip


def now() -> datetime:
    """The one clock of the to-do engine (garden-local, tz-aware); overridden in tests."""
    return datetime.now(TZ)


Now = Annotated[datetime, Depends(now)]


def today(n: Now) -> date:
    return n.date()


Today = Annotated[date, Depends(today)]

_plant_title = func.coalesce(
    plants.c.nickname,
    species.c.german[1] + func.coalesce(" \u2018" + cultivars.c.name + "\u2019", ""),
).label("plant_title")
_plant_join = (
    tasks.outerjoin(plants, plants.c.id == tasks.c.plant_id)
    .outerjoin(species, species.c.id == plants.c.species_id)
    .outerjoin(cultivars, cultivars.c.id == plants.c.cultivar_id)
    .outerjoin(standorte, standorte.c.id == plants.c.standort_id)
)
_active = and_(
    or_(tasks.c.plant_id.is_(None), plants.c.archived_at.is_(None)),  # plant not archived
    or_(tasks.c.category.not_in(INDOOR_CATEGORIES), standorte.c.type == INDOOR),  # watering: indoors only (F-CP-6)
)


# Plant facts the legal rules need (legal.py), selected next to every task.
FACTS = (
    species.c.woody.label("sp_woody"),
    species.c.growth.label("sp_growth"),
    species.c.latin.label("sp_latin"),
    plants.c.girth_cm.label("pl_girth"),
    standorte.c.type.label("st_type"),
)


def _timing(r: Any) -> TaskTiming:
    return TaskTiming(**{k: getattr(r, k) for k in TIMING})


def _facts(r: Any) -> PlantFacts | None:
    if not r.plant_id:
        return None
    return PlantFacts(r.sp_woody, r.sp_growth, is_fruit_tree(r.sp_latin, r.sp_growth), r.pl_girth,
                      r.st_type == INDOOR)  # fmt: skip


async def legal_settings(c: AsyncConnection) -> LegalSettings:
    data = (await c.execute(select(settings.c.data).where(settings.c.id == 1))).scalar()
    g = GardenSettings.model_validate(known_fields(GardenSettings, data or {}))
    return LegalSettings(
        g.location.bundesland, g.legal.baumschutz_girth_cm, g.legal.fruit_trees_exempt, g.preferences.eco_defaults
    )


def _notes(r: Any, s: LegalSettings, months: list[int]) -> list[dict[str, str]]:
    return [n.__dict__ for n in notes(r.category, r.cut_type, _facts(r), s, frozenset(months))]


def _months_between(a: date, b: date) -> list[int]:
    out: list[int] = []
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month) and len(out) < 12:
        out.append(m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _adjuster(r: Any, s: LegalSettings) -> Any:
    def adjust(a: date, b: date) -> tuple[date, date, str]:
        adj = adjust_window(r.category, r.cut_type, _facts(r), s, a, b)
        return adj.due_from, adj.due_to, adj.reason

    return adjust


def _task_out(r: Row[Any], s: LegalSettings, day: date) -> Task:
    fields = {k: getattr(r, k) for k in TaskIn.model_fields}
    plant = {"id": r.plant_id, "title": r.plant_title} if r.plant_id else None
    return Task(
        **fields,
        id=r.id,
        plant=plant,
        source=r.source,
        enabled=r.enabled,
        products=r.products,
        why=r.why,
        notes=_notes(r, s, months_in_year(_timing(r), day.year)),
        next_due=getattr(r, "next_due", None),
    )


def _todo_out(r: Row[Any], day: date, s: LegalSettings) -> dict[str, Any]:
    blocked = blocked_until(r.category, r.cut_type, _facts(r), s, day) if r.status == "open" else None
    return {
        "id": r.todo_id,
        "status": r.status,
        "due_from": r.due_from,
        "due_to": r.due_to,
        "overdue": r.status == "open" and r.due_to < day and blocked is None,
        "blocked_until": blocked,  # a strong cut that is not allowed today (§ 39): not "overdue"
        "postponed": r.postponed,
        "note": r.note,
        "soil": r.soil,
        "done_at": r.done_at,
        "task": {
            k: getattr(r, k) for k in ("id", "title", "category", "urgent", "instructions", "recurrence", "amount_ml")
        },
        "plant": {"id": r.plant_id, "title": r.plant_title} if r.plant_id else None,
        "legal_adjustment": r.legal_adjustment,
        "notes": _notes(r, s, _months_between(r.due_from, r.due_to)),
    }


_todo_query = select(
    todos.c.id.label("todo_id"),
    todos.c.status,
    todos.c.due_from,
    todos.c.due_to,
    todos.c.postponed,
    todos.c.note,
    todos.c.soil,
    todos.c.done_at,
    todos.c.legal_adjustment,
    tasks,
    _plant_title,
    *FACTS,
).select_from(_plant_join.join(todos, todos.c.task_id == tasks.c.id))


async def materialize(c: AsyncConnection, day: date, task_ids: list[str] | None = None) -> None:
    """Create the occurrences that should exist on `day` (idempotent). Task rows are
    share-locked, so a concurrent timing change cannot interleave with this."""
    q = (
        select(tasks, *FACTS)
        .select_from(_plant_join)
        .where(tasks.c.enabled, _active)
        .with_for_update(read=True, of=tasks)
    )
    if task_ids is not None:
        q = q.where(tasks.c.id.in_(task_ids))
    rows = (await c.execute(q)).all()
    if not rows:
        return
    interval_ids = [r.id for r in rows if r.recurrence == "interval"]
    open_now: set[str] = set()
    last_closed: dict[str, datetime] = {}
    if interval_ids:
        open_now = set(
            (
                await c.execute(
                    select(todos.c.task_id).where(todos.c.task_id.in_(interval_ids), todos.c.status == "open")
                )
            ).scalars()
        )
        last_closed = {
            r.task_id: r.last
            for r in await c.execute(
                select(todos.c.task_id, func.max(todos.c.done_at).label("last"))
                .where(todos.c.task_id.in_(interval_ids), todos.c.status != "open")
                .group_by(todos.c.task_id)
            )
        }
    stamp = datetime.now(UTC)  # record keeping only; due dates come from `day`
    s = await legal_settings(c)
    starts = await safe_phase_starts(c, day) if any(r.pheno_phase for r in rows) else {}
    values = []
    for r in rows:
        adjust = _adjuster(r, s)  # the legal rules move or shorten windows before anything is stored
        if r.recurrence != "interval":
            start = (lambda y, k=r.pheno_phase: starts.get((y, k))) if r.pheno_phase else None
            found = occurrences(_timing(r), day, adjust, phase_start=start)
        elif r.id in open_now:
            found = []
        else:
            last = last_closed.get(r.id)
            after_last = interval_after(last.astimezone(TZ).date(), _timing(r)) if last else None
            if after_last is not None:
                a, b, why = adjust(after_last.due_from, after_last.due_to)
                after_last = Occurrence(after_last.period, a, b, why)
            first = occurrences(_timing(r), day, adjust)  # start_date or today
            use_start = after_last is None or (r.start_date is not None and r.start_date > after_last.due_from)
            found = first if use_start else [after_last] if after_last else []
            found = [o for o in found if o.due_from <= day + timedelta(days=HORIZON_DAYS)]
        values += [
            {
                "id": uuid.uuid4().hex,
                "task_id": r.id,
                "generation": r.generation,
                "period": o.period,
                "due_from": o.due_from,
                "due_to": o.due_to,
                "status": "open",
                "note": "",
                "postponed": False,
                "legal_adjustment": o.reason or None,
                "created_at": stamp,
            }
            for o in found
        ]
    if values:
        await c.execute(pg_insert(todos).values(values).on_conflict_do_nothing(constraint="uq_todos_task_period"))
    triggered = {r.id: r for r in rows if r.pheno_phase and r.recurrence == "yearly"}
    if triggered and starts:
        await _follow_phases(c, triggered, starts, s)


async def _follow_phases(
    c: AsyncConnection, triggered: dict[str, Any], starts: dict[tuple[int, str], date], s: LegalSettings
) -> None:
    """The phase was reported (or observed) after the to-do was made: open to-dos follow it,
    also when the new window lies beyond the horizon. Postponed ones stay where the user put
    them. One query for all, an update only where the dates differ."""
    rows = await c.execute(
        select(todos.c.id, todos.c.task_id, todos.c.period, todos.c.due_from, todos.c.due_to).where(
            todos.c.task_id.in_(list(triggered)), todos.c.status == "open", todos.c.postponed.is_(False)
        )
    )
    for t in rows:
        r = triggered[t.task_id]
        if not t.period.isdigit():
            continue
        phase: str = r.pheno_phase

        def phase_start(y: int, phase: str = phase) -> date | None:
            return starts.get((y, phase))

        start, end = yearly_span(_timing(r), int(t.period), phase_start)
        a, b, why = _adjuster(r, s)(start, end)
        if (a, b) != (t.due_from, t.due_to):
            await c.execute(
                update(todos).where(todos.c.id == t.id).values(due_from=a, due_to=b, legal_adjustment=why or None)
            )


async def _check_plant(c: AsyncConnection, body: TaskIn) -> None:
    found = None
    if body.plant_id:
        found = (
            await c.execute(
                select(standorte.c.type).select_from(plants.join(standorte)).where(plants.c.id == body.plant_id)
            )
        ).first()
        if found is None:
            raise invalid("plant_id", "unknown plant")
    if body.category in INDOOR_CATEGORIES and (found is None or found.type != INDOOR):
        raise invalid("category", "only for indoor plants")  # the garden is not watered (F-CP-6)


async def _one_task(c: AsyncConnection, tid: str, day: date) -> Task:
    q = select(tasks, _plant_title, *FACTS).select_from(_plant_join).where(tasks.c.id == tid)
    row = (await c.execute(q)).first()
    if row is None:
        raise not_found("task")
    return _task_out(row, await legal_settings(c), day)


# ----- tasks ---------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(
    c: Conn,
    day: Today,
    plant_id: Annotated[str | None, Query(max_length=120)] = None,
    retired: bool = False,  # also tasks of replaced care plans (history)
) -> list[Task]:
    is_open = (todos.c.task_id == tasks.c.id, todos.c.status == "open")
    due_now = select(func.max(todos.c.due_from)).where(*is_open, todos.c.due_from <= day).scalar_subquery()
    coming = select(func.min(todos.c.due_from)).where(*is_open, todos.c.due_from > day).scalar_subquery()
    nxt = case((_active, func.coalesce(due_now, coming)), else_=None).label("next_due")
    q = select(tasks, _plant_title, nxt, *FACTS).select_from(_plant_join).order_by(tasks.c.title)
    if not retired:
        q = q.where(~tasks.c.retired)
    if plant_id:
        q = q.where(tasks.c.plant_id == plant_id)
    s = await legal_settings(c)
    return [_task_out(r, s, day) for r in await c.execute(q)]


@router.get("/tasks/{tid}")
async def read_task(tid: str, c: Conn, day: Today) -> Task:
    return await _one_task(c, tid, day)


@router.post("/tasks", status_code=201)
async def create_task(body: TaskIn, c: Conn, day: Today) -> Task:
    await _check_plant(c, body)
    stamp = datetime.now(UTC)
    tid = uuid.uuid4().hex
    values = body.model_dump() | {
        "id": tid,
        "source": "manual",
        "enabled": True,
        "generation": 1,
        "created_at": stamp,
        "updated_at": stamp,
    }
    await c.execute(insert(tasks).values(values))
    await materialize(c, day, [tid])
    return await _one_task(c, tid, day)


@router.put("/tasks/{tid}")
async def update_task(tid: str, body: TaskIn, c: Conn, day: Today) -> Task:
    old = (await c.execute(select(tasks).where(tasks.c.id == tid).with_for_update())).first()
    if old is None:
        raise not_found("task")
    await _check_plant(c, body)
    values: dict[str, Any] = body.model_dump() | {"updated_at": datetime.now(UTC)}
    if old.source == "plan":  # edited by hand: survives the next plan (F-CP-7)
        values["source"] = "manual"
    rule_fields = ("category", "cut_type", "plant_id")  # the legal rules depend on these (review M4)
    if _timing(old) != _timing(body) or any(
        getattr(old, f) != getattr(body, f) for f in rule_fields
    ):  # new generation: history stays, open ones are replaced
        values["generation"] = old.generation + 1
        await c.execute(delete(todos).where(todos.c.task_id == tid, todos.c.status == "open"))
    await c.execute(update(tasks).where(tasks.c.id == tid).values(values))
    await materialize(c, day, [tid])
    return await _one_task(c, tid, day)


async def _set_enabled(c: AsyncConnection, tid: str, enabled: bool, day: date) -> Task:
    row = (await c.execute(select(tasks).where(tasks.c.id == tid).with_for_update())).first()
    if row is None:
        raise not_found("task")
    if row.retired and enabled:  # its plan was replaced; the new plan has its own task
        raise ApiError(409, "task belongs to a replaced plan")
    if enabled:  # the plant may have moved outside meanwhile
        await _check_plant(c, TaskIn.model_validate({k: getattr(row, k) for k in TaskIn.model_fields}))
    await c.execute(update(tasks).where(tasks.c.id == tid).values(enabled=enabled))
    if enabled:
        await materialize(c, day, [tid])
    else:  # only open ones go; done/skipped history stays
        await c.execute(delete(todos).where(todos.c.task_id == tid, todos.c.status == "open"))
    return await _one_task(c, tid, day)


@router.post("/tasks/{tid}/disable")
async def disable_task(tid: str, c: Conn, day: Today) -> Task:
    return await _set_enabled(c, tid, False, day)


@router.post("/tasks/{tid}/enable")
async def enable_task(tid: str, c: Conn, day: Today) -> Task:
    return await _set_enabled(c, tid, True, day)


# ----- checklist -----------------------------------------------------------


def _month(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


@router.get("/todos/heute")
async def heute(c: Conn, day: Today) -> dict[str, Any]:
    """Open to-dos due up to the end of this month (newest per task; overdue, then
    urgent first) and what was done or skipped this month (newest first)."""
    await materialize(c, day)
    return await month_list(c, day)


async def month_list(c: AsyncConnection, day: date) -> dict[str, Any]:
    """Heute's list as stored (no new occurrences): also for the chat's read-only role."""
    first, last = _month(day)
    open_rows = await c.execute(
        _todo_query.where(todos.c.status == "open", todos.c.due_from <= last, tasks.c.enabled, _active).order_by(
            todos.c.due_from.desc()
        )
    )
    newest: dict[str, Row[Any]] = {}
    for r in open_rows:
        newest.setdefault(r.id, r)  # rows come newest first; r.id is the task id
    open_list = sorted(
        newest.values(), key=lambda r: (r.due_to >= day, not r.urgent, r.due_from, r.title)
    )  # overdue, urgent, date, title
    since = datetime.combine(first, time(), TZ)
    until = datetime.combine(last + timedelta(days=1), time(), TZ)
    done_rows = await c.execute(
        _todo_query.where(todos.c.status != "open", todos.c.done_at >= since, todos.c.done_at < until).order_by(
            todos.c.done_at.desc()
        )
    )
    s = await legal_settings(c)
    return {
        "year": day.year,
        "month": day.month,
        "open": [_todo_out(r, day, s) for r in open_list],
        "done": [_todo_out(r, day, s) for r in done_rows],
    }


async def _todo(c: AsyncConnection, todo_id: str, day: date) -> dict[str, Any]:
    row = (await c.execute(_todo_query.where(todos.c.id == todo_id))).first()
    if row is None:
        raise not_found("to-do")
    return _todo_out(row, day, await legal_settings(c))


@router.get("/todos/{todo_id}")
async def read_todo(todo_id: str, c: Conn, day: Today) -> dict[str, Any]:
    return await _todo(c, todo_id, day)


async def _close(c: AsyncConnection, todo_id: str, status: str, body: NoteIn, at: datetime) -> dict[str, Any]:
    values: dict[str, Any] = {"status": status, "done_at": at}
    if body.note is not None:
        values["note"] = body.note
    task_id = (
        await c.execute(update(todos).where(todos.c.id == todo_id).values(values).returning(todos.c.task_id))
    ).scalar()
    if task_id is None:
        raise not_found("to-do")
    await materialize(c, at.date(), [task_id])  # interval: next one after this
    return await _todo(c, todo_id, at.date())


@router.post("/todos/{todo_id}/done")
async def done(todo_id: str, body: NoteIn, c: Conn, at: Now) -> dict[str, Any]:
    return await _close(c, todo_id, "done", body, at)


@router.post("/todos/{todo_id}/skip")
async def skip(todo_id: str, body: NoteIn, c: Conn, at: Now) -> dict[str, Any]:
    return await _close(c, todo_id, "skipped", body, at)


@router.post("/todos/{todo_id}/undo")
async def undo(todo_id: str, c: Conn, day: Today) -> dict[str, Any]:
    row = (
        await c.execute(
            select(
                todos.c.task_id,
                todos.c.generation,
                todos.c.period,
                todos.c.note,
                tasks.c.generation.label("task_gen"),
                tasks.c.recurrence,
            )
            .join(tasks)
            .where(todos.c.id == todo_id)
            .with_for_update(of=tasks)
        )
    ).first()
    if row is None:
        raise not_found("to-do")
    if row.generation != row.task_gen:
        raise ApiError(409, "the task was changed since; this entry is history")
    if row.recurrence == "interval":  # the next one was planned from this one: plan it anew
        await c.execute(
            delete(todos).where(
                todos.c.task_id == row.task_id,
                todos.c.status == "open",
                todos.c.note == "",
                todos.c.postponed.is_(False),
            )
        )
    if row.period.startswith("extra-"):  # "heute gemacht" without a due to-do: history only, no to-do to reopen
        await c.execute(delete(todos).where(todos.c.id == todo_id))
        await materialize(c, day, [row.task_id])
        return {"id": todo_id, "status": "removed"}
    values: dict[str, Any] = {"status": "open", "done_at": None, "soil": None}
    if row.note == WET_NOTE:  # "später" taken back (the longer rhythm stays: the soil was moist)
        values["note"] = ""
    await c.execute(update(todos).where(todos.c.id == todo_id).values(values))
    return await _todo(c, todo_id, day)


SOIL_FACTOR = {"feucht": 1.2, "passt": 1.0, "trocken": 0.8}
MIN_WATER, MAX_WATER = 2, 60


def adjusted(days: int, soil: str) -> int:
    """The next watering interval after "the soil was still moist / just right / bone dry": ±20 %,
    at least one day, within 2..60 days."""
    if soil == "feucht":
        return max(days, min(MAX_WATER, max(days + 1, round(days * SOIL_FACTOR[soil]))))
    if soil == "trocken":
        return min(days, max(MIN_WATER, min(days - 1, round(days * SOIL_FACTOR[soil]))))
    return days


@router.post("/todos/{todo_id}/soil")
async def soil_feedback(todo_id: str, body: SoilIn, c: Conn, day: Today) -> dict[str, Any]:
    """After watering: how the soil was. Changes the rhythm in use now (winter or summer) once."""
    claimed = await c.execute(  # first: exactly one answer per watering, also from two phones at once
        update(todos)
        .where(todos.c.id == todo_id, todos.c.status == "done", todos.c.soil.is_(None))
        .values(soil=body.soil)
        .returning(todos.c.task_id, todos.c.generation, todos.c.done_at)
    )
    done = claimed.first()
    if done is None:
        if (await c.execute(select(todos.c.id).where(todos.c.id == todo_id))).first() is None:
            raise not_found("to-do")
        raise ApiError(409, "only once, after watering")
    row = (await c.execute(select(tasks).where(tasks.c.id == done.task_id).with_for_update())).one()
    if row.category != "giessen" or row.recurrence != "interval" or row.generation != done.generation:
        raise ApiError(409, "only once, after watering")  # rolls back the claim
    field = rhythm_field(done.done_at.astimezone(TZ).date(), _timing(row))
    new = adjusted(getattr(row, field), body.soil)
    if new != getattr(row, field):  # the next one was planned with the old rhythm: plan it anew
        await c.execute(update(tasks).where(tasks.c.id == row.id).values({field: new, "updated_at": datetime.now(UTC)}))
        await c.execute(delete(todos).where(todos.c.task_id == row.id, todos.c.status == "open",
                                            todos.c.postponed.is_(False), todos.c.note == ""))  # fmt: skip
        await materialize(c, day, [row.id])
    return await _todo(c, todo_id, day)


RECHECK_PART = 4  # "noch zu feucht": look again after a quarter of the rhythm (at least 2 days)
WET_NOTE = "noch zu feucht"


@router.post("/todos/{todo_id}/later")
async def still_wet(todo_id: str, c: Conn, at: Now) -> dict[str, Any]:
    """Watering or misting is due, but the soil (or the air) is still moist: skip it, water
    less often from now on (like "noch feucht") and look again in a few days."""
    day = at.date()
    claimed = await c.execute(
        update(todos)
        .where(todos.c.id == todo_id, todos.c.status == "open", todos.c.due_from <= day)  # not before it is due
        .values(status="skipped", done_at=at, soil="feucht", note=WET_NOTE)
        .returning(todos.c.task_id, todos.c.generation)
    )
    got = claimed.first()
    if got is None:
        if (await c.execute(select(todos.c.id).where(todos.c.id == todo_id))).first() is None:
            raise not_found("to-do")
        raise ApiError(409, "only for an open watering or misting")
    row = (await c.execute(select(tasks).where(tasks.c.id == got.task_id).with_for_update())).one()
    if row.category not in ("giessen", "bespruehen") or row.recurrence != "interval":
        raise ApiError(409, "only for an open watering or misting")  # rolls back
    field = rhythm_field(day, _timing(row))
    new = adjusted(getattr(row, field), "feucht")
    await c.execute(update(tasks).where(tasks.c.id == row.id).values({field: new, "updated_at": datetime.now(UTC)}))
    await c.execute(delete(todos).where(todos.c.task_id == row.id, todos.c.status == "open",
                                        todos.c.postponed.is_(False), todos.c.note == ""))  # fmt: skip
    again = in_season(_timing(row), day + timedelta(days=max(2, round(new / RECHECK_PART))))
    await c.execute(
        pg_insert(todos)
        .values(id=uuid.uuid4().hex, task_id=row.id, generation=row.generation, period=f"recheck-{again.isoformat()}",
                due_from=again, due_to=again, status="open", note="", postponed=False, created_at=datetime.now(UTC))
        .on_conflict_do_nothing(constraint="uq_todos_task_period")
    )  # fmt: skip
    return await _todo(c, todo_id, day)


@router.post("/tasks/{tid}/done-now")
async def done_now(tid: str, body: NoteIn, c: Conn, at: Now) -> dict[str, Any]:
    """Done today, whenever it was due ("heute gemacht" on the plant page): the next open
    to-do is closed; without one the entry is history only. An interval counts from today."""
    row = (await c.execute(select(tasks).where(tasks.c.id == tid).with_for_update())).first()
    if row is None:
        raise not_found("task")
    if not row.enabled or row.retired:
        raise ApiError(409, "task is paused")
    await _check_plant(c, TaskIn.model_validate({k: getattr(row, k) for k in TaskIn.model_fields}))
    values: dict[str, Any] = {"status": "done", "done_at": at}
    if body.note is not None:
        values["note"] = body.note
    open_rows = (
        await c.execute(select(todos.c.id, todos.c.due_from).where(todos.c.task_id == tid, todos.c.status == "open"))
    ).all()
    due = [r for r in open_rows if r.due_from <= at.date()]  # like Heute: the newest one due now, else the next
    pick = max(due, key=lambda r: r.due_from) if due else min(open_rows, key=lambda r: r.due_from, default=None)
    nxt = pick.id if pick is not None else None
    if nxt is not None:
        await c.execute(update(todos).where(todos.c.id == nxt).values(values))
        todo_id = nxt
    else:
        todo_id = uuid.uuid4().hex
        await c.execute(insert(todos).values(
            id=todo_id, task_id=tid, generation=row.generation, period=f"extra-{todo_id[:12]}", due_from=at.date(),
            due_to=at.date(), status="done", done_at=at, note=body.note or "", postponed=False,
            created_at=datetime.now(UTC),
        ))  # fmt: skip
    await materialize(c, at.date(), [tid])  # an interval: the next one from today
    return await _todo(c, todo_id, at.date())


@router.post("/todos/{todo_id}/postpone")
async def postpone(todo_id: str, body: PostponeIn, c: Conn, day: Today) -> dict[str, Any]:
    if body.to <= day:
        raise invalid("to", "must be after today")
    task = (
        await c.execute(
            select(tasks, *FACTS)
            .select_from(_plant_join.join(todos, todos.c.task_id == tasks.c.id))
            .where(todos.c.id == todo_id)
        )
    ).first()
    if task is not None:  # the legal rules apply to a postponed date as well (review M4)
        adj = adjust_window(task.category, task.cut_type, _facts(task), await legal_settings(c), body.to, body.to)
        if adj.kind:
            raise invalid("to", f"{adj.reason} Frühestens am {adj.due_from:%d.%m.%Y}.")
    result = await c.execute(
        update(todos)
        .where(todos.c.id == todo_id, todos.c.status == "open")
        .values(due_from=body.to, due_to=body.to, postponed=True)
    )
    if result.rowcount == 0:
        if (await c.execute(select(todos.c.id).where(todos.c.id == todo_id))).first() is None:
            raise not_found("to-do")
        raise ApiError(409, "only open to-dos can be postponed")
    return await _todo(c, todo_id, day)


# ----- calendar --------------------------------------------------------------


@router.get("/calendar")
async def calendar_year(c: Conn, year: Annotated[int, Query(ge=2000, le=2100)]) -> dict[str, Any]:
    """Enabled tasks of active plants projected onto the months of `year` (not stored)."""
    result = await c.execute(
        select(tasks, _plant_title, *FACTS)
        .select_from(_plant_join)
        .where(tasks.c.enabled, _active)
        .order_by(tasks.c.title)
    )
    rows = result.all()
    s = await legal_settings(c)
    today = datetime.now(TZ).date()
    near = abs(year - today.year) <= 1  # phase dates exist for last, this and next year
    starts = await safe_phase_starts(c, today) if near and any(r.pheno_phase for r in rows) else {}
    months: list[list[dict[str, Any]]] = [[] for _ in range(12)]
    for r in rows:
        entry = {
            "task_id": r.id,
            "title": r.title,
            "category": r.category,
            "urgent": r.urgent,
            "plant": {"id": r.plant_id, "title": r.plant_title} if r.plant_id else None,
        }
        found = months_in_year(_timing(r), year)
        spans = [yearly_span(_timing(r), y, {y: d}.get) for y in (year - 1, year)
                 if r.pheno_phase and (d := starts.get((y, r.pheno_phase))) is not None]  # fmt: skip
        if spans:  # the season's windows reaching into this year, not the fallback months (ticket 033)
            found = sorted({(a + timedelta(days=i)).month for a, b in spans for i in range((b - a).days + 1)
                            if (a + timedelta(days=i)).year == year})  # fmt: skip
        elif r.recurrence == "yearly" and r.month_from > r.month_to:  # window order: Nov, Dec, Jan, Feb
            found = [m for m in found if m >= r.month_from] + [m for m in found if m < r.month_from]
        allowed, moved = allowed_months(r.category, r.cut_type, _facts(r), s, found)
        for m in allowed:
            months[m - 1].append(entry | {"moved": m in moved})
    return {"year": year, "months": months}


# ----- legal preview for the task form ----------------------------------------------


@router.post("/legal/preview")
async def legal_preview(body: TaskIn, c: Conn, day: Today) -> dict[str, Any]:
    """Notes and the next (possibly moved) window of a task that is being edited."""
    await _check_plant(c, body)
    q = select(plants.c.id.label("plant_id"), *FACTS).select_from(
        plants.join(species, species.c.id == plants.c.species_id).join(
            standorte, standorte.c.id == plants.c.standort_id
        )
    )
    row = (await c.execute(q.where(plants.c.id == body.plant_id))).first() if body.plant_id else None
    r = _Probe(body, row)
    s = await legal_settings(c)
    starts = await safe_phase_starts(c, day) if body.pheno_phase else {}
    start = (lambda y, k=body.pheno_phase: starts.get((y, k))) if body.pheno_phase else None
    upcoming = occurrences(_timing(r), day, _adjuster(r, s), horizon_days=400, phase_start=start)  # next real date
    nxt = upcoming[0] if upcoming else None
    return {
        "notes": _notes(r, s, months_in_year(_timing(r), day.year)),
        "next": {"due_from": nxt.due_from, "due_to": nxt.due_to, "reason": nxt.reason} if nxt else None,
    }


class _Probe:
    """A TaskIn plus plant facts, shaped like a task row for the helpers above."""

    def __init__(self, body: TaskIn, plant: Any) -> None:
        self.__dict__.update(body.model_dump())
        self.plant_id = body.plant_id if plant is not None else None
        for k in ("sp_woody", "sp_growth", "sp_latin", "pl_girth", "st_type"):
            setattr(self, k, getattr(plant, k) if plant is not None else None)
