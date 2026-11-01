"""Care plan per plant (M5): queue a Claude run, read the latest plan and job.
The api only queues; the worker (internet) runs Claude and stores the result."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from blattwerk.catalog import ready
from blattwerk.db import Conn
from blattwerk.errors import ApiError, not_found
from blattwerk.jobs import fail_stale, used_today
from blattwerk.routes.todos import TZ
from blattwerk.schema import care_plans, plan_jobs, plants

router = APIRouter(dependencies=[Depends(ready)])


@router.post("/plants/{pid}/plan", status_code=202)
async def request_plan(pid: str, c: Conn, request: Request) -> dict[str, str]:
    plant = (await c.execute(select(plants.c.archived_at).where(plants.c.id == pid).with_for_update())).first()
    if plant is None:
        raise not_found("plant")
    if plant.archived_at is not None:
        raise ApiError(409, "plant is archived")
    if await used_today(c, plan_jobs, TZ) >= request.app.state.config.plan_daily_limit:
        raise ApiError(429, "daily plan limit reached")
    jid = await queue_plan(c, pid, request.app.state.config.plan_daily_limit)
    if jid is None:
        raise ApiError(409, "a plan is already being made for this plant")
    return {"job_id": jid}


async def queue_plan(c: AsyncConnection, pid: str, daily_limit: int) -> str | None:
    """Queue a plan for the plant; None when one is already on its way or the day's limit is
    reached (then the plant page offers the button). Also used when a plant is added."""
    if await used_today(c, plan_jobs, TZ) >= daily_limit:
        return None
    await fail_stale(c, plan_jobs)
    busy = await c.execute(
        select(plan_jobs.c.id).where(plan_jobs.c.plant_id == pid, plan_jobs.c.status.in_(("queued", "running")))
    )
    if busy.first() is not None:
        return None
    jid = uuid.uuid4().hex
    await c.execute(insert(plan_jobs).values(id=jid, plant_id=pid, status="queued", created_at=datetime.now(UTC)))
    return jid


@router.get("/plants/{pid}/plan")
async def read_plan(pid: str, c: Conn) -> dict[str, Any]:
    if (await c.execute(select(plants.c.id).where(plants.c.id == pid))).first() is None:
        raise not_found("plant")
    plan = (
        await c.execute(select(care_plans).where(care_plans.c.plant_id == pid).order_by(care_plans.c.created_at.desc()))
    ).first()
    job = (
        await c.execute(
            select(
                plan_jobs.c.id, plan_jobs.c.status, plan_jobs.c.error, plan_jobs.c.created_at, plan_jobs.c.finished_at
            )
            .where(plan_jobs.c.plant_id == pid)
            .order_by(plan_jobs.c.created_at.desc())
        )
    ).first()
    plan_out = None
    if plan is not None:
        keys = ("id", "created_at", "model", "prompt_version", "summary", "confidence", "caveats", "pests", "dropped")
        plan_out = {k: getattr(plan, k) for k in keys}
    return {"plan": plan_out, "job": job._asdict() if job is not None else None}
