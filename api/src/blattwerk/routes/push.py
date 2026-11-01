"""Push subscriptions per device (F-TD-6). The api only stores them and writes
the outbox; the worker container sends. Endpoints are restricted to the real
push services (models.Endpoint), so no user-supplied URL is ever contacted."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from blattwerk.db import Conn
from blattwerk.errors import ApiError, not_found
from blattwerk.models import EndpointIn, PushSubIn
from blattwerk.schema import push_subs
from blattwerk.worker import enqueue

router = APIRouter()
MAX_DEVICES = 20  # keeps a full outbox run short (worker healthcheck) and bounds abuse


@router.get("/push/key")
async def public_key(request: Request) -> dict[str, str | None]:
    return {"public_key": request.app.state.config.vapid_public or None}


@router.post("/push/subscriptions", status_code=201)
async def subscribe(body: PushSubIn, c: Conn, response: Response) -> dict[str, str]:
    values = {"p256dh": body.keys.p256dh, "auth": body.keys.auth, "label": body.label}
    found = (await c.execute(select(push_subs.c.id).where(push_subs.c.endpoint == body.endpoint))).scalar()
    if found:
        await c.execute(update(push_subs).where(push_subs.c.id == found).values(values))
        response.status_code = 200
        return {"id": found}
    if (await c.execute(select(func.count()).select_from(push_subs))).scalar_one() >= MAX_DEVICES:
        raise ApiError(409, "too many devices")
    sid = uuid.uuid4().hex
    stmt = insert(push_subs).values(id=sid, endpoint=body.endpoint, created_at=datetime.now(UTC), **values)
    await c.execute(stmt.on_conflict_do_update(index_elements=["endpoint"], set_=values))
    return {"id": sid}


@router.post("/push/unsubscribe", status_code=204)
async def unsubscribe(body: EndpointIn, c: Conn) -> Response:
    await c.execute(delete(push_subs).where(push_subs.c.endpoint == body.endpoint))
    return Response(status_code=204)


@router.post("/push/test", status_code=202)
async def test_message(body: EndpointIn, c: Conn) -> dict[str, str]:
    sid = (await c.execute(select(push_subs.c.id).where(push_subs.c.endpoint == body.endpoint))).scalar()
    if sid is None:
        raise not_found("subscription")
    await enqueue(c, [sid], "Test vom Blattwerk", "Push funktioniert auf diesem Gerät.", "/#/mehr")
    return {"status": "queued"}
