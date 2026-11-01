"""Garden settings (F-ST-1/3): one row with a JSONB document, full replace on PUT.
Reading ignores fields this version does not know (after a rollback)."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from blattwerk.db import Conn
from blattwerk.models import GardenSettings, known_fields
from blattwerk.schema import settings

router = APIRouter()
SCHEMA_VERSION = 1


@router.get("/settings")
async def read_settings(c: Conn) -> GardenSettings:
    data = (await c.execute(select(settings.c.data).where(settings.c.id == 1))).scalar()
    return GardenSettings.model_validate(known_fields(GardenSettings, data or {}))


@router.put("/settings")
async def write_settings(body: GardenSettings, c: Conn) -> GardenSettings:
    row = {"id": 1, "data": body.model_dump(), "schema_version": SCHEMA_VERSION}
    stmt = insert(settings).values(row)
    await c.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"], set_={"data": stmt.excluded.data, "schema_version": stmt.excluded.schema_version}
        )
    )
    return body
