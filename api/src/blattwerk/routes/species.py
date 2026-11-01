"""Species master data: name resolver for the "add plant" screen, species
detail with Sorten, and user additions (source "user") when the seed lacks one.
Additions commit in their own transaction and invalidate the catalog after the
commit, so no request can cache a catalog without them."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from blattwerk.catalog import invalidate, ready
from blattwerk.db import Conn, get_engine
from blattwerk.errors import ApiError, constraint_of, not_found
from blattwerk.models import CultivarIn, SpeciesIn, SpeciesTraits
from blattwerk.resolver import Catalog, cultivar_id, fold, resolve
from blattwerk.schema import cultivars, species

router = APIRouter(dependencies=[Depends(ready)])


@router.get("/species/resolve")
async def resolve_name(
    catalog: Annotated[Catalog, Depends(ready)], q: Annotated[str, Query(max_length=200)] = ""
) -> dict[str, list[dict[str, Any]]]:
    found = await run_in_threadpool(resolve, catalog, q)  # CPU work: keep the event loop free
    return {"candidates": [asdict(c) for c in found]}


@router.get("/species/{sid}")
async def read_species(sid: str, c: Conn) -> dict[str, Any]:
    row = (await c.execute(select(species).where(species.c.id == sid))).first()
    if row is None:
        raise not_found("species")
    cults = await c.execute(
        select(cultivars.c.id, cultivars.c.name, cultivars.c.source)
        .where(cultivars.c.species_id == sid)
        .order_by(cultivars.c.name)
    )
    return {**row._asdict(), "cultivars": [r._asdict() for r in cults]}


@router.post("/species", status_code=201)
async def create_species(body: SpeciesIn, request: Request) -> dict[str, Any]:
    sid = "-".join(fold(w) for w in body.latin.split() if fold(w))
    values = body.model_dump() | {"id": sid, "family": None, "synonyms": [], "feeder": None, "source": "user"}
    try:
        async with get_engine(request).begin() as c:
            await c.execute(insert(species).values(values))
    except IntegrityError as e:
        if constraint_of(e) in ("pk_species", "species_pkey", "uq_species_latin"):
            raise ApiError(409, "species exists") from None
        raise
    invalidate(request)
    return values


@router.put("/species/{sid}")
async def update_species(sid: str, body: SpeciesTraits, request: Request) -> dict[str, Any]:
    """Only species the app added (source "user"): German names, growth, woody. Seed species
    are reviewed data and stay as they are."""
    async with get_engine(request).begin() as c:
        row = (await c.execute(select(species.c.source).where(species.c.id == sid).with_for_update())).first()
        if row is None:
            raise not_found("species")
        if row.source != "user":
            raise ApiError(409, "built-in species cannot be changed")
        await c.execute(update(species).where(species.c.id == sid).values(**body.model_dump()))
        out = (await c.execute(select(species).where(species.c.id == sid))).one()
    invalidate(request)
    return dict(out._asdict())


@router.post("/species/{sid}/cultivars", status_code=201)
async def create_cultivar(sid: str, body: CultivarIn, request: Request, response: Response) -> dict[str, str]:
    """Idempotent: the same Sorte in another spelling ("BALLERINA", "Gräfin"/"Graefin")
    answers 200 with the existing one, so the client never loses the choice."""
    cid = cultivar_id(sid, body.name)
    async with get_engine(request).begin() as c:
        if (await c.execute(select(species.c.id).where(species.c.id == sid))).first() is None:
            raise not_found("species")
        stmt = (
            pg_insert(cultivars)
            .values(id=cid, species_id=sid, name=body.name, synonyms=[], source="user")
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(cultivars.c.id)
        )
        created = (await c.execute(stmt)).first() is not None
        row = (await c.execute(select(cultivars).where(cultivars.c.id == cid))).one()
    if created:
        invalidate(request)
    else:
        response.status_code = 200
    return {"id": row.id, "name": row.name, "source": row.source}
