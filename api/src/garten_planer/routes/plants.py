"""Plants (F-PL-2/3/5). References to species, Sorte (of that species) and
Standort are checked on every write; answers carry the names, so the UI needs
one request per screen. Never hard-deleted: archive / restore keeps history."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from garten_planer.catalog import ready
from garten_planer.db import Db, get_db
from garten_planer.errors import invalid, not_found
from garten_planer.models import Plant, PlantIn

router = APIRouter(dependencies=[Depends(ready)])


async def _check_refs(db: Db, body: PlantIn) -> None:
    if await db.species.count_documents({"_id": body.species_id}) == 0:
        raise invalid("species_id", "unknown species")
    if body.cultivar_id is not None and (
        await db.cultivars.count_documents({"_id": body.cultivar_id, "species_id": body.species_id}) == 0
    ):
        raise invalid("cultivar_id", "unknown Sorte for this species")
    if await db.standorte.count_documents({"_id": body.standort_id}) == 0:
        raise invalid("standort_id", "unknown Standort")


async def _expand(db: Db, docs: list[dict[str, Any]]) -> list[Plant]:
    """Batch-load the referenced species, Sorten and Standorte (3 queries)."""

    async def by_id(coll: str, ids: set[str]) -> dict[str, dict[str, Any]]:
        return {d["_id"]: d async for d in db[coll].find({"_id": {"$in": sorted(ids)}})}

    species = await by_id("species", {d["species_id"] for d in docs})
    cultivars = await by_id("cultivars", {d["cultivar_id"] for d in docs if d.get("cultivar_id")})
    standorte = await by_id("standorte", {d["standort_id"] for d in docs})
    out = []
    for d in docs:
        sp, cu = species[d["species_id"]], cultivars.get(d.get("cultivar_id") or "")
        # A Standort deleted while this plant was saved (two phones) must not break the list.
        st = standorte.get(d["standort_id"], {"_id": d["standort_id"], "name": "(gelöscht)", "light": None})
        fields = {k: d.get(k) for k in PlantIn.model_fields if k not in ("species_id", "cultivar_id", "standort_id")}
        out.append(
            Plant.model_validate(
                {
                    **fields,
                    "id": d["_id"],
                    "species": {
                        "id": sp["_id"],
                        "latin": sp["latin"],
                        "german": (sp.get("german") or [sp["latin"]])[0],
                        "growth": sp["growth"],
                        "woody": sp["woody"],
                    },
                    "cultivar": {"id": cu["_id"], "name": cu["name"]} if cu else None,
                    "standort": {"id": st["_id"], "name": st["name"], "light": st["light"]},
                    "archived": d.get("archived_at") is not None,
                }
            )
        )
    return sorted(out, key=lambda p: (p.standort.name.lower(), (p.nickname or p.species.german).lower()))


async def _one(db: Db, pid: str) -> Plant:
    doc = await db.plants.find_one({"_id": pid})
    if doc is None:
        raise not_found("plant")
    return (await _expand(db, [doc]))[0]


@router.get("/plants")
async def list_plants(request: Request, archived: Annotated[bool, Query()] = False) -> list[Plant]:
    db = get_db(request)
    query = {"archived_at": {"$ne": None}} if archived else {"archived_at": None}
    return await _expand(db, [d async for d in db.plants.find(query)])


@router.get("/plants/{pid}")
async def read_plant(pid: str, request: Request) -> Plant:
    return await _one(get_db(request), pid)


@router.post("/plants", status_code=201)
async def create_plant(body: PlantIn, request: Request) -> Plant:
    db = get_db(request)
    await _check_refs(db, body)
    now = datetime.now(UTC)
    pid = uuid.uuid4().hex
    await db.plants.insert_one(
        {
            "_id": pid,
            **body.model_dump(),
            "archived_at": None,
            "created_at": now,
            "updated_at": now,
            "schema_version": 1,
        }
    )
    return await _one(db, pid)


@router.put("/plants/{pid}")
async def update_plant(pid: str, body: PlantIn, request: Request) -> Plant:
    db = get_db(request)
    if await db.plants.count_documents({"_id": pid}) == 0:
        raise not_found("plant")
    await _check_refs(db, body)
    await db.plants.update_one({"_id": pid}, {"$set": {**body.model_dump(), "updated_at": datetime.now(UTC)}})
    return await _one(db, pid)


async def _set_archived(request: Request, pid: str, archived: bool) -> Plant:
    db = get_db(request)
    now = datetime.now(UTC)
    result = await db.plants.update_one(
        {"_id": pid}, {"$set": {"archived_at": now if archived else None, "updated_at": now}}
    )
    if result.matched_count == 0:
        raise not_found("plant")
    return await _one(db, pid)


@router.post("/plants/{pid}/archive")
async def archive_plant(pid: str, request: Request) -> Plant:
    return await _set_archived(request, pid, True)


@router.post("/plants/{pid}/restore")
async def restore_plant(pid: str, request: Request) -> Plant:
    return await _set_archived(request, pid, False)
