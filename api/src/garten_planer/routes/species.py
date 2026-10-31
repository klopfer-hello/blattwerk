"""Species master data: name resolver for the "add plant" screen, species
detail with Sorten, and user additions (source "user") when the seed lacks one."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pymongo.errors import DuplicateKeyError

from garten_planer.catalog import invalidate, ready
from garten_planer.db import get_db
from garten_planer.errors import ApiError, not_found
from garten_planer.models import CultivarIn, SpeciesIn
from garten_planer.resolver import Catalog, cultivar_id, fold, resolve

router = APIRouter(dependencies=[Depends(ready)])


@router.get("/species/resolve")
async def resolve_name(
    catalog: Annotated[Catalog, Depends(ready)], q: Annotated[str, Query(max_length=200)] = ""
) -> dict[str, list[dict[str, Any]]]:
    found = await run_in_threadpool(resolve, catalog, q)  # CPU work: keep the event loop free
    return {"candidates": [asdict(c) for c in found]}


@router.get("/species/{sid}")
async def read_species(sid: str, request: Request) -> dict[str, Any]:
    db = get_db(request)
    doc = await db.species.find_one({"_id": sid})
    if doc is None:
        raise not_found("species")
    cultivars = [
        {"id": c["_id"], "name": c["name"], "source": c["source"]}
        async for c in db.cultivars.find({"species_id": sid}).sort("name")
    ]
    return {"id": doc.pop("_id"), **doc, "cultivars": cultivars}


@router.post("/species", status_code=201)
async def create_species(body: SpeciesIn, request: Request) -> dict[str, Any]:
    sid = "-".join(fold(w) for w in body.latin.split() if fold(w))
    doc = {"_id": sid, **body.model_dump(), "family": None, "synonyms": [], "feeder": None, "source": "user"}
    try:
        await get_db(request).species.insert_one(doc)
    except DuplicateKeyError:
        raise ApiError(409, "species exists") from None
    invalidate(request)
    return {"id": doc.pop("_id"), **doc}


@router.post("/species/{sid}/cultivars", status_code=201)
async def create_cultivar(sid: str, body: CultivarIn, request: Request, response: Response) -> dict[str, str]:
    """Idempotent: the same Sorte in another spelling ("BALLERINA", "Gräfin"/"Graefin")
    answers 200 with the existing one, so the client never loses the choice."""
    db = get_db(request)
    if await db.species.count_documents({"_id": sid}) == 0:
        raise not_found("species")
    cid = cultivar_id(sid, body.name)
    existing = await db.cultivars.find_one({"_id": cid})
    if existing is None:
        try:
            await db.cultivars.insert_one(
                {"_id": cid, "species_id": sid, "name": body.name, "synonyms": [], "source": "user"}
            )
            invalidate(request)
            return {"id": cid, "name": body.name, "source": "user"}
        except DuplicateKeyError:  # created by another request in between
            existing = await db.cultivars.find_one({"_id": cid})
    if existing is None:
        raise ApiError(409, "Sorte exists")
    response.status_code = 200
    return {"id": existing["_id"], "name": existing["name"], "source": existing["source"]}
