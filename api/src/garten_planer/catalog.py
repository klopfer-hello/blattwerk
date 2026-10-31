"""Species master data in the DB and the in-memory name catalog.

Done lazily on the first request that needs it (not at start-up), so the API
still starts and /healthz answers 503 while the DB is down. `ready()` upserts
the shipped seed (source "seed"; user additions stay untouched) and builds the
resolver Catalog; `invalidate()` after user additions. A generation counter
keeps a catalog built before a concurrent invalidation from being cached."""

from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from garten_planer.db import get_engine
from garten_planer.resolver import Catalog, CultivarData, SpeciesData, cultivar_id
from garten_planer.schema import cultivars, species
from garten_planer.seed import load_seed


async def _setup(c: AsyncConnection) -> None:
    seed = load_seed().species
    rows = [s.model_dump(exclude={"cultivars"}) | {"source": "seed"} for s in seed]
    stmt = insert(species).values(rows)
    await c.execute(
        stmt.on_conflict_do_update(index_elements=["id"], set_={k: stmt.excluded[k] for k in rows[0] if k != "id"})
    )
    crows = [
        {
            "id": cultivar_id(s.id, cu.name),
            "species_id": s.id,
            "name": cu.name,
            "synonyms": cu.synonyms,
            "source": "seed",
        }
        for s in seed
        for cu in s.cultivars
    ]
    cstmt = insert(cultivars).values(crows)
    await c.execute(
        cstmt.on_conflict_do_update(
            index_elements=["id"], set_={k: cstmt.excluded[k] for k in ("name", "synonyms", "source")}
        )
    )


async def _build(c: AsyncConnection) -> Catalog:
    sp = [SpeciesData(r.id, r.latin, tuple(r.german), tuple(r.synonyms)) for r in await c.execute(select(species))]
    cu = [CultivarData(r.id, r.species_id, r.name, tuple(r.synonyms)) for r in await c.execute(select(cultivars))]
    return Catalog(sp, cu)


async def ready(request: Request) -> Catalog:
    """FastAPI dependency: DB seeded, catalog built (once per app)."""
    app: FastAPI = request.app
    state: Any = app.state
    if state.catalog is None:
        async with state.ready_lock:  # created per app in the lifespan (locks bind to one loop)
            if not state.seeded:
                async with get_engine(request).begin() as c:
                    await _setup(c)
                state.seeded = True
            if state.catalog is None:
                generation = state.catalog_gen
                async with get_engine(request).connect() as c:
                    built = await _build(c)
                if state.catalog_gen != generation:  # a Sorte was added meanwhile: use, do not keep
                    return built
                state.catalog = built
    catalog: Catalog = state.catalog
    return catalog


def invalidate(request: Request) -> None:
    request.app.state.catalog_gen += 1
    request.app.state.catalog = None
