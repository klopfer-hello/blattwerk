"""Phenological season (M7, F-WX-2/6): GET the season state for the garden, and the
user's own observations ("Forsythie blüht bei mir"), which win over the region."""

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Response
from pydantic import AfterValidator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from blattwerk import pheno
from blattwerk.db import Conn
from blattwerk.errors import ApiError, not_found
from blattwerk.models import Strict
from blattwerk.routes.todos import TZ
from blattwerk.schema import kv, pheno_events, pheno_normals
from blattwerk.season_dates import season_core

router = APIRouter()
PhaseKey = Literal[
    "vorfruehling", "erstfruehling", "vollfruehling", "fruehsommer", "hochsommer", "spaetsommer", "fruehherbst",
    "vollherbst", "spaetherbst", "winter",
]  # fmt: skip


def _recent(d: date) -> date:
    today = datetime.now(TZ).date()
    if d > today or d.year < today.year - 1:
        raise ValueError("day must be in this or last year and not in the future")
    return d


class Observation(Strict):
    phase: PhaseKey
    day: Annotated[date, AfterValidator(_recent)]

    @model_validator(mode="after")
    def _year(self) -> Observation:
        if self.day.year < datetime.now(TZ).date().year and self.phase != "winter":
            raise ValueError("only the winter of last year can be recorded for last year")
        return self


async def season_state(c: AsyncConnection, today: date) -> dict[str, Any]:
    state = await season_core(c, today)
    state["gdd"] = None
    gdd = (await c.execute(select(kv.c.value).where(kv.c.key == "gdd"))).scalar()
    try:
        if gdd and gdd.get("year") == today.year and isinstance(gdd.get("curve"), dict) and gdd["curve"]:
            as_of = date.fromisoformat(gdd["as_of"])
            curve: dict[str, float] = gdd["curve"]
            state["gdd"] = {
                "sum": float(gdd["sum"]), "as_of": gdd["as_of"], "normal": curve.get(pheno.mmdd(as_of)),
                "days_ahead": pheno.days_ahead(float(gdd["sum"]), as_of, curve),
            }  # fmt: skip
    except KeyError, TypeError, ValueError:
        state["gdd"] = None  # odd stored data: the season without the warmth comparison
    return state


@router.get("/season")
async def read_season(c: Conn) -> dict[str, Any]:
    return await season_state(c, datetime.now(TZ).date())


@router.post("/season/observations", status_code=201)
async def observe(body: Observation, c: Conn) -> dict[str, Any]:
    norm = {r.phase: (r.doy, r.stations) for r in await c.execute(select(pheno_normals))}
    if pheno.implausible(body.phase, body.day, norm):
        raise ApiError(422, "observation far from the phase's usual time", {"day": "implausible"})
    stmt = pg_insert(pheno_events).values(
        year=pheno.reference_year(body.phase, body.day),
        phase=body.phase,
        source="garten",
        day=body.day,
        reports=1,
        updated_at=datetime.now(UTC),
    )
    await c.execute(
        stmt.on_conflict_do_update(
            index_elements=["year", "phase", "source"],
            set_={"day": stmt.excluded.day, "updated_at": stmt.excluded.updated_at},
        )
    )
    return await season_state(c, datetime.now(TZ).date())


@router.delete("/season/observations/{phase}", status_code=204)
async def unobserve(phase: str, c: Conn) -> Response:
    year = datetime.now(TZ).date().year
    gone = await c.execute(  # this year, or last year's winter
        delete(pheno_events).where(
            pheno_events.c.year.in_((year, year - 1)), pheno_events.c.phase == phase, pheno_events.c.source == "garten"
        )
    )
    if gone.rowcount == 0:
        raise not_found("observation")
    return Response(status_code=204)
