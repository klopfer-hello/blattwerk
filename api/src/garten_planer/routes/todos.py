"""To-do engine over HTTP (F-TD): tasks (what, when), their occurrences (the
checklist), and the calendar projection.

Rules (simple on purpose, after review M3a):
- Occurrences are created idempotently by `materialize` (UNIQUE task, generation,
  period) whenever a task changes, an occurrence is closed, and when Heute is read.
- Interval tasks: if nothing is open, the next one is due at "last done/skipped +
  n days" (or start_date / today without history). This one rule covers done,
  undo, pause/resume and interval changes.
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
from sqlalchemy import Row, delete, func, insert, or_, select, update
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
from garten_planer.models import GardenSettings, NoteIn, PostponeIn, Task, TaskIn, known_fields
from garten_planer.schedule import HORIZON_DAYS, Occurrence, TaskTiming, interval_after, months_in_year, occurrences
from garten_planer.schema import cultivars, plants, settings, species, tasks, todos

router = APIRouter(dependencies=[Depends(ready)])
TZ = ZoneInfo("Europe/Berlin")
TIMING = ("recurrence", "due_date", "month_from", "month_to", "interval_days", "start_date")


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
)
_active = or_(tasks.c.plant_id.is_(None), plants.c.archived_at.is_(None))  # plant not archived


# Plant facts the legal rules need (legal.py), selected next to every task.
FACTS = (
    species.c.woody.label("sp_woody"),
    species.c.growth.label("sp_growth"),
    species.c.latin.label("sp_latin"),
    plants.c.girth_cm.label("pl_girth"),
)


def _timing(r: Any) -> TaskTiming:
    return TaskTiming(**{k: getattr(r, k) for k in TIMING})


def _facts(r: Any) -> PlantFacts | None:
    if not r.plant_id:
        return None
    return PlantFacts(r.sp_woody, r.sp_growth, is_fruit_tree(r.sp_latin, r.sp_growth), r.pl_girth)


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
        notes=_notes(r, s, months_in_year(_timing(r), day.year)),
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
        "done_at": r.done_at,
        "task": {k: getattr(r, k) for k in ("id", "title", "category", "urgent", "instructions", "recurrence")},
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
    values = []
    for r in rows:
        adjust = _adjuster(r, s)  # the legal rules move or shorten windows before anything is stored
        if r.recurrence != "interval":
            found = occurrences(_timing(r), day, adjust)
        elif r.id in open_now:
            found = []
        else:
            last = last_closed.get(r.id)
            after_last = interval_after(last.astimezone(TZ).date(), r.interval_days) if last else None
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


async def _check_plant(c: AsyncConnection, body: TaskIn) -> None:
    if body.plant_id and (await c.execute(select(plants.c.id).where(plants.c.id == body.plant_id))).first() is None:
        raise invalid("plant_id", "unknown plant")


async def _one_task(c: AsyncConnection, tid: str, day: date) -> Task:
    q = select(tasks, _plant_title, *FACTS).select_from(_plant_join).where(tasks.c.id == tid)
    row = (await c.execute(q)).first()
    if row is None:
        raise not_found("task")
    return _task_out(row, await legal_settings(c), day)


# ----- tasks ---------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(c: Conn, day: Today, plant_id: Annotated[str | None, Query(max_length=120)] = None) -> list[Task]:
    q = select(tasks, _plant_title, *FACTS).select_from(_plant_join).order_by(tasks.c.title)
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
    if (await c.execute(update(tasks).where(tasks.c.id == tid).values(enabled=enabled))).rowcount == 0:
        raise not_found("task")
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
            select(todos.c.task_id, todos.c.generation, tasks.c.generation.label("task_gen"), tasks.c.recurrence)
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
    await c.execute(update(todos).where(todos.c.id == todo_id).values(status="open", done_at=None))
    return await _todo(c, todo_id, day)


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
    rows = await c.execute(
        select(tasks, _plant_title, *FACTS)
        .select_from(_plant_join)
        .where(tasks.c.enabled, _active)
        .order_by(tasks.c.title)
    )
    s = await legal_settings(c)
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
        if r.recurrence == "yearly" and r.month_from > r.month_to:  # window order: Nov, Dec, Jan, Feb
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
        plants.join(species, species.c.id == plants.c.species_id)
    )
    row = (await c.execute(q.where(plants.c.id == body.plant_id))).first() if body.plant_id else None
    r = _Probe(body, row)
    s = await legal_settings(c)
    upcoming = occurrences(_timing(r), day, _adjuster(r, s), horizon_days=400)  # the next real date, even if far
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
        for k in ("sp_woody", "sp_growth", "sp_latin", "pl_girth"):
            setattr(self, k, getattr(plant, k) if plant is not None else None)
