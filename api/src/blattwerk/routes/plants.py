"""Plants (F-PL-2/3/5). References are checked for field-level error messages;
the DB enforces them too (FKs, Sorte of the same species). Answers carry the
names, so the UI needs one request per screen. Never hard-deleted: archive /
restore keeps history."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Row, Select, delete, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from blattwerk.catalog import ready
from blattwerk.db import Conn
from blattwerk.errors import invalid, not_found
from blattwerk.models import Plant, PlantIn
from blattwerk.routes.plans import queue_plan
from blattwerk.schema import (
    INDOOR,
    INDOOR_CATEGORIES,
    cultivars,
    diagnoses,
    plants,
    species,
    standorte,
    tasks,
    todos,
)

router = APIRouter(dependencies=[Depends(ready)])

_FIELDS = [k for k in PlantIn.model_fields if k not in ("species_id", "cultivar_id", "standort_id")]
_query: Select[Any] = (
    select(
        plants,
        species.c.latin,
        species.c.german,
        species.c.growth,
        species.c.woody,
        cultivars.c.name.label("cultivar_name"),
        standorte.c.name.label("standort_name"),
        standorte.c.light,
        standorte.c.type.label("standort_type"),
        standorte.c.windows,
    )
    .join(species, species.c.id == plants.c.species_id)
    .join(standorte, standorte.c.id == plants.c.standort_id)
    .outerjoin(cultivars, cultivars.c.id == plants.c.cultivar_id)
)


def _out(r: Row[Any]) -> Plant:
    return Plant.model_validate(
        {
            **{k: getattr(r, k) for k in _FIELDS},
            "id": r.id,
            "species": {
                "id": r.species_id,
                "latin": r.latin,
                "german": (r.german or [r.latin])[0],
                "growth": r.growth,
                "woody": r.woody,
            },
            "cultivar": {"id": r.cultivar_id, "name": r.cultivar_name} if r.cultivar_id else None,
            "standort": {
                "id": r.standort_id,
                "name": r.standort_name,
                "light": r.light,
                "type": r.standort_type,
                "indoor": r.standort_type == INDOOR,
                "windows": r.windows,
            },
            "archived": r.archived_at is not None,
        }
    )


async def _check_refs(c: AsyncConnection, body: PlantIn) -> bool:
    """Checks the references; returns whether the plant is indoors (its Standort is a Zimmer)."""

    async def has(stmt: Any) -> bool:
        return bool((await c.execute(select(exists(stmt)))).scalar())

    if not await has(select(species.c.id).where(species.c.id == body.species_id)):
        raise invalid("species_id", "unknown species")
    if body.cultivar_id is not None and not await has(
        select(cultivars.c.id).where(cultivars.c.id == body.cultivar_id, cultivars.c.species_id == body.species_id)
    ):
        raise invalid("cultivar_id", "unknown Sorte for this species")
    found = (
        await c.execute(select(standorte.c.type, standorte.c.windows).where(standorte.c.id == body.standort_id))
    ).first()
    if found is None:
        raise invalid("standort_id", "unknown Standort")
    if found.type != INDOOR and body.indoor_fields():
        raise invalid("window_dir", "window and pot only for indoor plants")
    if body.window_dir is not None and body.window_dir not in found.windows:  # one of the room's windows
        raise invalid("window_dir", "the room has no window in this direction")
    return bool(found.type == INDOOR)


async def _one(c: AsyncConnection, pid: str) -> Plant:
    row = (await c.execute(_query.where(plants.c.id == pid))).first()
    if row is None:
        raise not_found("plant")
    return _out(row)


@router.get("/plants")
async def list_plants(c: Conn, archived: Annotated[bool, Query()] = False) -> list[Plant]:
    cond = plants.c.archived_at.is_not(None) if archived else plants.c.archived_at.is_(None)
    rows = await c.execute(_query.where(cond))
    return sorted(
        (_out(r) for r in rows), key=lambda p: (p.standort.name.lower(), (p.nickname or p.species.german).lower())
    )


@router.get("/plants/{pid}")
async def read_plant(pid: str, c: Conn) -> Plant:
    return await _one(c, pid)


@router.post("/plants", status_code=201)
async def create_plant(body: PlantIn, c: Conn, request: Request) -> Plant:
    await _check_refs(c, body)
    now = datetime.now(UTC)
    pid = uuid.uuid4().hex
    await c.execute(insert(plants).values(body.model_dump() | {"id": pid, "created_at": now, "updated_at": now}))
    await queue_plan(c, pid, request.app.state.config.plan_daily_limit)  # the care plan comes by itself
    return await _one(c, pid)


@router.put("/plants/{pid}")
async def update_plant(pid: str, body: PlantIn, c: Conn, request: Request) -> Plant:
    old = (
        await c.execute(
            select(
                plants.c.species_id,
                plants.c.cultivar_id,
                plants.c.window_dir,
                plants.c.window_distance,
                plants.c.pot_cm,
                plants.c.pot_material,
                plants.c.height_cm,
                standorte.c.type,
            )
            .join(standorte, standorte.c.id == plants.c.standort_id)
            .where(plants.c.id == pid)
        )
    ).first()
    if old is None:
        raise not_found("plant")
    indoor = await _check_refs(c, body)
    await c.execute(
        update(plants).where(plants.c.id == pid).values(body.model_dump() | {"updated_at": datetime.now(UTC)})
    )
    moved = (old.type == INDOOR) != indoor
    if moved and not indoor:  # moved outside: the garden is not watered (F-CP-6); history stays
        watering = select(tasks.c.id).where(tasks.c.plant_id == pid, tasks.c.category.in_(INDOOR_CATEGORIES))
        await c.execute(update(tasks).where(tasks.c.id.in_(watering)).values(enabled=False))
        await c.execute(delete(todos).where(todos.c.task_id.in_(watering), todos.c.status == "open"))
    room = ("window_dir", "window_distance", "pot_cm", "pot_material", "height_cm")  # they set the watering
    changed_room = indoor and any(getattr(old, k) != getattr(body, k) for k in room)
    if moved or changed_room or (old.species_id, old.cultivar_id) != (body.species_id, body.cultivar_id):
        await queue_plan(c, pid, request.app.state.config.plan_daily_limit)
    return await _one(c, pid)


async def _set_archived(c: AsyncConnection, pid: str, archived: bool) -> Plant:
    now = datetime.now(UTC)
    stmt = update(plants).where(plants.c.id == pid).values(archived_at=now if archived else None, updated_at=now)
    if (await c.execute(stmt)).rowcount == 0:
        raise not_found("plant")
    return await _one(c, pid)


@router.post("/plants/{pid}/archive")
async def archive_plant(pid: str, c: Conn) -> Plant:
    return await _set_archived(c, pid, True)


@router.post("/plants/{pid}/restore")
async def restore_plant(pid: str, c: Conn) -> Plant:
    return await _set_archived(c, pid, False)


@router.get("/plants/{pid}/history")
async def plant_history(pid: str, c: Conn) -> list[dict[str, Any]]:
    """Done and skipped to-dos plus saved diagnoses, newest first (the plant's Verlauf tab)."""
    await _one(c, pid)
    done = await c.execute(
        select(todos.c.id, todos.c.status, todos.c.done_at, todos.c.note, tasks.c.title, tasks.c.category)
        .join(tasks, tasks.c.id == todos.c.task_id)
        .where(tasks.c.plant_id == pid, todos.c.status != "open")
        .order_by(todos.c.done_at.desc()).limit(100)
    )  # fmt: skip
    found = await c.execute(select(diagnoses).where(diagnoses.c.plant_id == pid)
                            .order_by(diagnoses.c.created_at.desc()).limit(100))  # fmt: skip
    items = [
        {"kind": "aufgabe", "id": r.id, "at": r.done_at, "title": r.title, "category": r.category,
         "status": r.status, "note": r.note}
        for r in done
    ] + [
        {"kind": "diagnose", "id": d.id, "at": d.created_at, "title": d.title,
         "confidence": d.confidence, "cause": d.cause, "photos": d.photo_ids}
        for d in found
    ]  # fmt: skip
    items.sort(key=lambda i: i["at"], reverse=True)  # datetimes, not strings: offsets differ across DST
    return [i | {"at": i["at"].isoformat()} for i in items]
