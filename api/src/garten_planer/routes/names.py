"""AI name suggestions (F-AI-3): queue a lookup for the worker, read the candidates
(marked when the species is already known), and pick one: the species (source
"user") and Sorte are created once, so the offline resolver finds them next time."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from pydantic.functional_validators import BeforeValidator
from sqlalchemy import func, insert, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from garten_planer.catalog import invalidate, ready
from garten_planer.db import Conn, get_engine
from garten_planer.errors import ApiError, not_found
from garten_planer.jobs import NAME_QUEUED_FOR, fail_stale, used_today
from garten_planer.models import Strict, _strip
from garten_planer.names import Suggestion
from garten_planer.resolver import cultivar_id, fold
from garten_planer.routes.todos import TZ
from garten_planer.schema import cultivars, name_jobs, species

router = APIRouter(dependencies=[Depends(ready)])


class NameQuery(Strict):
    q: Annotated[str, BeforeValidator(_strip), Field(min_length=2, max_length=200)]


class Pick(Strict):
    index: Annotated[int, Field(ge=0, le=9)]


NAME_QUEUE_MAX = 5  # open lookups at once: a stuck client cannot queue a day's budget


def _species_id(latin: str) -> str:
    return "-".join(fold(w) for w in latin.split() if fold(w))


async def _known(c: AsyncConnection, latin: str) -> str | None:
    """By Latin name or by the id it would get ("Allium porrum" -> seed "allium-porrum")."""
    found = await c.execute(
        select(species.c.id).where(
            or_(func.lower(species.c.latin) == latin.lower(), species.c.id == _species_id(latin))
        )
    )
    return found.scalars().first()


async def _genus_traits(c: AsyncConnection, latin: str) -> tuple[bool | None, str | None]:
    """What the seed says about the genus. Woodiness decides § 39, so the seed beats the AI;
    growth only when the whole genus agrees (Prunus has trees and shrubs)."""
    rows = (
        await c.execute(
            select(species.c.woody, species.c.growth).where(
                species.c.source == "seed", species.c.latin.like(latin.split()[0] + " %")
            )
        )
    ).all()
    woody = {r.woody for r in rows}
    growth = {r.growth for r in rows}
    return (woody.pop() if len(woody) == 1 else None), (growth.pop() if len(growth) == 1 else None)


@router.post("/species/ai", status_code=202)
async def request_names(body: NameQuery, c: Conn, request: Request) -> dict[str, str]:
    await fail_stale(c, name_jobs, queued_for=NAME_QUEUED_FOR)
    same = await c.execute(
        select(name_jobs.c.id).where(name_jobs.c.query == body.q, name_jobs.c.status.in_(("queued", "running")))
    )
    if (jid := same.scalars().first()) is not None:  # double tap or the same name again: one paid run
        return {"job_id": jid}
    if await used_today(c, name_jobs, TZ, "created_at") >= request.app.state.config.name_daily_limit:
        raise ApiError(429, "daily name limit reached")
    open_jobs = await c.execute(
        select(func.count()).select_from(name_jobs).where(name_jobs.c.status.in_(("queued", "running")))
    )
    if open_jobs.scalar_one() >= NAME_QUEUE_MAX:
        raise ApiError(429, "too many open name lookups")
    jid = uuid.uuid4().hex
    await c.execute(insert(name_jobs).values(id=jid, query=body.q, status="queued", created_at=datetime.now(UTC)))
    return {"job_id": jid}


@router.get("/species/ai/{jid}")
async def read_names(jid: str, c: Conn) -> dict[str, Any]:
    job = (await c.execute(select(name_jobs).where(name_jobs.c.id == jid))).first()
    if job is None:
        raise not_found("job")
    out = [cand | {"known_species_id": await _known(c, cand["latin"])} for cand in job.candidates]
    return {"id": job.id, "query": job.query, "status": job.status, "error": job.error, "candidates": out}


@router.post("/species/ai/{jid}/pick")
async def pick_name(jid: str, body: Pick, request: Request) -> dict[str, Any]:
    async with get_engine(request).begin() as c:
        job = (await c.execute(select(name_jobs).where(name_jobs.c.id == jid, name_jobs.c.status == "done"))).first()
        if job is None or body.index >= len(job.candidates):
            raise not_found("candidate")
        s = Suggestion.model_validate(job.candidates[body.index])
        sid = await _known(c, s.latin)
        if sid is None:
            woody, growth = await _genus_traits(c, s.latin)
            sid = _species_id(s.latin)
            await c.execute(
                pg_insert(species)
                .values(id=sid, latin=s.latin, family=s.family, german=s.german, synonyms=[],
                        growth=growth or s.growth, woody=s.woody if woody is None else woody,
                        hardiness_c=s.winterhaerte_c, feeder=None, source="user")
                .on_conflict_do_nothing()
            )  # fmt: skip
        row = (await c.execute(select(species.c.latin, species.c.german).where(species.c.id == sid))).one()
        cid = None
        if s.cultivar:
            cid = cultivar_id(sid, s.cultivar)
            await c.execute(
                pg_insert(cultivars)
                .values(id=cid, species_id=sid, name=s.cultivar, synonyms=[], source="user")
                .on_conflict_do_nothing(index_elements=["id"])
            )
    invalidate(request)
    return {
        "species_id": sid,
        "cultivar_id": cid,
        "latin": row.latin,
        "german": row.german[0],
        "form_hint": s.form_hint,
    }
