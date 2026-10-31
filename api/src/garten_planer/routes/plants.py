"""Plants (F-PL-2/3/5). References are checked for field-level error messages;
the DB enforces them too (FKs, Sorte of the same species). Answers carry the
names, so the UI needs one request per screen. Never hard-deleted: archive /
restore keeps history."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Row, Select, exists, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from garten_planer.catalog import ready
from garten_planer.db import Conn
from garten_planer.errors import invalid, not_found
from garten_planer.models import Plant, PlantIn
from garten_planer.routes.plans import queue_plan
from garten_planer.schema import cultivars, plants, species, standorte

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
            "standort": {"id": r.standort_id, "name": r.standort_name, "light": r.light},
            "archived": r.archived_at is not None,
        }
    )


async def _check_refs(c: AsyncConnection, body: PlantIn) -> None:
    async def has(stmt: Any) -> bool:
        return bool((await c.execute(select(exists(stmt)))).scalar())

    if not await has(select(species.c.id).where(species.c.id == body.species_id)):
        raise invalid("species_id", "unknown species")
    if body.cultivar_id is not None and not await has(
        select(cultivars.c.id).where(cultivars.c.id == body.cultivar_id, cultivars.c.species_id == body.species_id)
    ):
        raise invalid("cultivar_id", "unknown Sorte for this species")
    if not await has(select(standorte.c.id).where(standorte.c.id == body.standort_id)):
        raise invalid("standort_id", "unknown Standort")


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
    old = (await c.execute(select(plants.c.species_id, plants.c.cultivar_id).where(plants.c.id == pid))).first()
    if old is None:
        raise not_found("plant")
    await _check_refs(c, body)
    await c.execute(
        update(plants).where(plants.c.id == pid).values(body.model_dump() | {"updated_at": datetime.now(UTC)})
    )
    if (old.species_id, old.cultivar_id) != (body.species_id, body.cultivar_id):  # another plant now: new plan
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
