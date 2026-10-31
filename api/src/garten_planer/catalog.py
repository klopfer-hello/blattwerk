"""Species master data in the DB and the in-memory name catalog.

Done lazily on the first request that needs it (not at start-up), so the API
still starts and /healthz answers 503 while the DB is down. `ready()` upserts
the shipped seed (source "seed"; user additions stay untouched), creates the
indexes and builds the resolver Catalog; `invalidate()` after user additions."""

from typing import Any

from fastapi import FastAPI, Request
from pymongo import ReplaceOne

from garten_planer.db import Db, get_db
from garten_planer.resolver import Catalog, CultivarData, SpeciesData, cultivar_id
from garten_planer.seed import load_seed


async def _setup(db: Db) -> None:
    seed = load_seed().species
    species = [
        ReplaceOne({"_id": s.id}, s.model_dump(exclude={"id", "cultivars"}) | {"source": "seed"}, upsert=True)
        for s in seed
    ]
    cultivars = [
        ReplaceOne(
            {"_id": cultivar_id(s.id, c.name)},
            {"species_id": s.id, "name": c.name, "synonyms": c.synonyms, "source": "seed"},
            upsert=True,
        )
        for s in seed
        for c in s.cultivars
    ]
    await db.species.bulk_write(species, ordered=False)
    await db.cultivars.bulk_write(cultivars, ordered=False)
    await db.standorte.create_index("name_key", unique=True)
    await db.cultivars.create_index("species_id")
    await db.plants.create_index("standort_id")


async def _build(db: Db) -> Catalog:
    species = [
        SpeciesData(d["_id"], d["latin"], tuple(d.get("german", [])), tuple(d.get("synonyms", [])))
        async for d in db.species.find({})
    ]
    cultivars = [
        CultivarData(d["_id"], d["species_id"], d["name"], tuple(d.get("synonyms", [])))
        async for d in db.cultivars.find({})
    ]
    return Catalog(species, cultivars)


async def ready(request: Request) -> Catalog:
    """FastAPI dependency: DB seeded and indexed, catalog built (once per app)."""
    app: FastAPI = request.app
    state: Any = app.state
    if getattr(state, "catalog", None) is None:
        async with state.ready_lock:  # created per app in the lifespan (locks bind to one loop)
            if not getattr(state, "seeded", False):
                await _setup(get_db(request))
                state.seeded = True
            if getattr(state, "catalog", None) is None:
                generation = state.catalog_gen
                built = await _build(get_db(request))
                if state.catalog_gen != generation:  # a Sorte was added meanwhile: use, do not keep
                    return built
                state.catalog = built
    catalog: Catalog = state.catalog
    return catalog


def invalidate(request: Request) -> None:
    request.app.state.catalog_gen += 1
    request.app.state.catalog = None
