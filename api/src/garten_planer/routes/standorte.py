"""Standorte (F-ST-2). Names are unique ignoring case and umlaut spelling
(unique index on the folded name); a Standort that any plant (also archived)
refers to cannot be deleted, so plant history never points to nothing."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pymongo.errors import DuplicateKeyError, OperationFailure

from garten_planer.catalog import ready
from garten_planer.db import Db, get_db
from garten_planer.errors import ApiError, not_found
from garten_planer.models import Standort, StandortIn
from garten_planer.resolver import fold

router = APIRouter(dependencies=[Depends(ready)])
DUPLICATE = ApiError(409, "a Standort with this name exists")
DUP_CODE = 11000


async def _check_unique(db: Db, name: str, sid: str | None) -> None:
    """Explicit check: FerretDB reports a unique-index hit on findAndModify as a
    plain OperationFailure, not DuplicateKeyError. The index stays the guard."""
    other = await db.standorte.find_one({"name_key": fold(name)}, {"_id": 1})
    if other is not None and other["_id"] != sid:
        raise DUPLICATE


async def _out(db: Db, doc: dict[str, Any]) -> Standort:
    count = await db.plants.count_documents({"standort_id": doc["_id"], "archived_at": None})
    return Standort(id=doc["_id"], plant_count=count, **{k: doc[k] for k in StandortIn.model_fields})


@router.get("/standorte")
async def list_standorte(request: Request) -> list[Standort]:
    db = get_db(request)
    docs = [d async for d in db.standorte.find({}).sort("name_key")]
    return [await _out(db, d) for d in docs]


@router.post("/standorte", status_code=201)
async def create_standort(body: StandortIn, request: Request) -> Standort:
    db = get_db(request)
    await _check_unique(db, body.name, None)
    doc = {"_id": uuid.uuid4().hex, **body.model_dump(), "name_key": fold(body.name)}
    try:
        await db.standorte.insert_one(doc)
    except DuplicateKeyError:
        raise DUPLICATE from None
    return await _out(db, doc)


@router.put("/standorte/{sid}")
async def update_standort(sid: str, body: StandortIn, request: Request) -> Standort:
    db = get_db(request)
    await _check_unique(db, body.name, sid)
    try:
        doc = await db.standorte.find_one_and_update(
            {"_id": sid}, {"$set": {**body.model_dump(), "name_key": fold(body.name)}}, return_document=True
        )
    except OperationFailure as e:  # race with another write; includes DuplicateKeyError
        if e.code == DUP_CODE or "duplicate key" in str(e).lower():
            raise DUPLICATE from None
        raise
    if doc is None:
        raise not_found("Standort")
    return await _out(db, doc)


@router.delete("/standorte/{sid}", status_code=204)
async def delete_standort(sid: str, request: Request) -> Response:
    db = get_db(request)
    if await db.standorte.count_documents({"_id": sid}) == 0:
        raise not_found("Standort")
    if await db.plants.count_documents({"standort_id": sid}) > 0:
        raise ApiError(409, "Standort still has plants (also archived ones)")
    await db.standorte.delete_one({"_id": sid})
    return Response(status_code=204)
