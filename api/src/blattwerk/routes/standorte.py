"""Standorte (F-ST-2). Names are unique ignoring case and umlaut spelling (unique
folded key in the DB); a Standort that any plant (also archived) refers to
cannot be deleted (FK RESTRICT), so plant history never points to nothing. A Standort
with plants cannot switch between drinnen (zimmer) and draußen: watering and the weather
rules of its plants depend on it (M11)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import Row, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from blattwerk.catalog import ready
from blattwerk.db import Conn
from blattwerk.errors import ApiError, constraint_of, not_found
from blattwerk.models import Standort, StandortIn
from blattwerk.resolver import fold
from blattwerk.schema import INDOOR, plants, standorte

router = APIRouter(dependencies=[Depends(ready)])
DUPLICATE = ApiError(409, "a Standort with this name exists")
IN_USE = ApiError(409, "Standort still has plants (also archived ones)")

_active_count = (
    select(func.count())
    .where(plants.c.standort_id == standorte.c.id, plants.c.archived_at.is_(None))
    .scalar_subquery()
    .label("plant_count")
)


def _out(row: Row[Any]) -> Standort:
    return Standort(
        id=row.id,
        name=row.name,
        light=row.light,
        type=row.type,
        windows=row.windows,
        notes=row.notes,
        plant_count=row.plant_count,
    )


async def _one(c: AsyncConnection, sid: str) -> Standort:
    row = (await c.execute(select(standorte, _active_count).where(standorte.c.id == sid))).first()
    if row is None:
        raise not_found("Standort")
    return _out(row)


async def _write(c: AsyncConnection, stmt: Any) -> int:
    try:
        return int((await c.execute(stmt)).rowcount)
    except IntegrityError as e:
        if constraint_of(e) == "uq_standorte_name_key":
            raise DUPLICATE from None
        raise


@router.get("/standorte")
async def list_standorte(c: Conn) -> list[Standort]:
    return [_out(r) for r in await c.execute(select(standorte, _active_count).order_by(standorte.c.name_key))]


@router.post("/standorte", status_code=201)
async def create_standort(body: StandortIn, c: Conn) -> Standort:
    sid = uuid.uuid4().hex
    values = body.model_dump() | {"id": sid, "name_key": fold(body.name), "created_at": datetime.now(UTC)}
    await _write(c, insert(standorte).values(values))
    return await _one(c, sid)


@router.put("/standorte/{sid}")
async def update_standort(sid: str, body: StandortIn, c: Conn) -> Standort:
    old = (await c.execute(select(standorte.c.type).where(standorte.c.id == sid).with_for_update())).first()
    if old is not None and (old.type == INDOOR) != (body.type == INDOOR):
        used = await c.execute(select(func.count()).select_from(plants).where(plants.c.standort_id == sid))
        if used.scalar_one():
            raise ApiError(409, "Standort has plants: cannot switch between indoor and outdoor")
    values = body.model_dump() | {"name_key": fold(body.name)}
    if await _write(c, update(standorte).where(standorte.c.id == sid).values(values)) == 0:
        raise not_found("Standort")
    return await _one(c, sid)


@router.delete("/standorte/{sid}", status_code=204)
async def delete_standort(sid: str, c: Conn) -> Response:
    try:
        deleted = (await c.execute(delete(standorte).where(standorte.c.id == sid))).rowcount
    except IntegrityError as e:
        if constraint_of(e) == "fk_plants_standort_id":
            raise IN_USE from None
        raise
    if deleted == 0:
        raise not_found("Standort")
    return Response(status_code=204)
