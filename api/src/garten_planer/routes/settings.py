"""Garden settings (F-ST-1/3): one document, full replace on PUT."""

from fastapi import APIRouter, Request

from garten_planer.db import get_db
from garten_planer.models import GardenSettings, known_fields

router = APIRouter()
DOC_ID = "garden"
SCHEMA_VERSION = 1


@router.get("/settings")
async def read_settings(request: Request) -> GardenSettings:
    doc = await get_db(request).settings.find_one({"_id": DOC_ID}, {"_id": 0, "schema_version": 0})
    return GardenSettings.model_validate(known_fields(GardenSettings, doc or {}))


@router.put("/settings")
async def write_settings(body: GardenSettings, request: Request) -> GardenSettings:
    doc = {"schema_version": SCHEMA_VERSION, **body.model_dump()}
    await get_db(request).settings.replace_one({"_id": DOC_ID}, doc, upsert=True)
    return body
