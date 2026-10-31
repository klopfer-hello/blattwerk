"""Garden chat API (M8, F-AI-4): chats and messages, the answer streamed as server-sent
events while the worker writes it, and the user's decision on proposals. The api only
queues and reads; the worker (with internet) runs Claude."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BeforeValidator, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from garten_planer.chat import MAX_QUESTION
from garten_planer.db import Conn, get_engine
from garten_planer.errors import ApiError, not_found
from garten_planer.garten_tools import active_plant, check_task, indoor_plant
from garten_planer.jobs import CHAT_QUEUED_FOR, CHAT_STALE, fail_stale
from garten_planer.models import Strict, _strip
from garten_planer.routes.todos import TZ, create_task
from garten_planer.schema import chat_actions, chat_messages, chats, diagnoses, photos, plants, species, tasks

router = APIRouter()
STREAM_POLL_S = 0.4
STREAM_MAX_S = 6 * 60
PING_S = 15
NOTES_MAX = 1000
PROPOSAL_DAYS = timedelta(days=7)  # an old card does not create a task in the past
MAX_PHOTOS = 3


class Question(Strict):
    text: Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=MAX_QUESTION)]
    photo_ids: list[Annotated[str, Field(max_length=64)]] = Field(default=[], max_length=MAX_PHOTOS)
    plant_id: str | None = None  # "Pflanze krank?": the question is about this plant (kept for the chat)


async def _plant_context(c: AsyncConnection, chat_id: str, plant_id: str | None) -> None:
    if plant_id is None:
        return
    if not await active_plant(c, plant_id):
        raise ApiError(422, "unknown plant", {"plant_id": "unknown"})
    await c.execute(update(chats).where(chats.c.id == chat_id).values(plant_id=plant_id))


async def _claim_photos(c: AsyncConnection, message_id: str, ids: list[str]) -> None:
    """Fresh uploads only: each photo belongs to exactly one question."""
    if not ids:
        return
    claimed = await c.execute(
        update(photos).where(photos.c.id.in_(ids), photos.c.message_id.is_(None)).values(message_id=message_id)
    )
    if len(set(ids)) != len(ids) or claimed.rowcount != len(ids):
        raise ApiError(422, "unknown or already used photo", {"photo_ids": "invalid"})


async def _ask(c: AsyncConnection, chat_id: str, question: str, limit: int, photo_ids: list[str] | None = None) -> str:
    photo_ids = photo_ids or []
    await fail_stale(c, chat_messages, CHAT_STALE, queued_for=CHAT_QUEUED_FOR)
    midnight = datetime.combine(datetime.now(TZ).date(), datetime.min.time(), TZ)
    asked = await c.execute(
        select(func.count()).select_from(chat_messages)
        .where(chat_messages.c.role == "assistant", chat_messages.c.created_at >= midnight,
               ~((chat_messages.c.status == "failed") & chat_messages.c.started_at.is_(None)))
    )  # fmt: skip
    if asked.scalar_one() >= limit:
        raise ApiError(429, "daily chat limit reached")
    stamp = datetime.now(UTC)
    qid = uuid.uuid4().hex
    await c.execute(chat_messages.insert().values(id=qid, chat_id=chat_id, role="user", text=question,
                                                  photos=photo_ids, status="done", created_at=stamp))  # fmt: skip
    await _claim_photos(c, qid, photo_ids)
    mid = uuid.uuid4().hex
    await c.execute(chat_messages.insert().values(id=mid, chat_id=chat_id, role="assistant", text="", status="queued",
                                                  created_at=stamp + timedelta(microseconds=1)))  # fmt: skip
    await c.execute(update(chats).where(chats.c.id == chat_id).values(updated_at=stamp))
    return mid


@router.get("/chats")
async def list_chats(c: Conn) -> list[dict[str, Any]]:
    rows = await c.execute(select(chats).order_by(chats.c.updated_at.desc()).limit(50))
    return [{"id": r.id, "title": r.title, "updated_at": r.updated_at.isoformat()} for r in rows]


@router.post("/chats", status_code=201)
async def new_chat(body: Question, c: Conn, request: Request) -> dict[str, str]:
    cid = uuid.uuid4().hex
    stamp = datetime.now(UTC)
    title = body.text if len(body.text) <= 60 else body.text[:57].rstrip() + " …"
    await c.execute(chats.insert().values(id=cid, title=title, created_at=stamp, updated_at=stamp))
    await _plant_context(c, cid, body.plant_id)
    mid = await _ask(c, cid, body.text, request.app.state.config.chat_daily_limit, body.photo_ids)
    return {"chat_id": cid, "message_id": mid}


@router.post("/chats/{cid}/messages", status_code=202)
async def add_message(cid: str, body: Question, c: Conn, request: Request) -> dict[str, str]:
    if (await c.execute(select(chats.c.id).where(chats.c.id == cid).with_for_update())).first() is None:
        raise not_found("chat")
    await fail_stale(c, chat_messages, CHAT_STALE, queued_for=CHAT_QUEUED_FOR)  # an expired answer frees the chat
    busy = await c.execute(
        select(chat_messages.c.id).where(chat_messages.c.chat_id == cid,
                                         chat_messages.c.status.in_(("queued", "running")))
    )  # fmt: skip
    if busy.first() is not None:
        raise ApiError(409, "the previous answer is still being written")
    await _plant_context(c, cid, body.plant_id)
    mid = await _ask(c, cid, body.text, request.app.state.config.chat_daily_limit, body.photo_ids)
    return {"chat_id": cid, "message_id": mid}


@router.get("/chats/{cid}")
async def read_chat(cid: str, c: Conn) -> dict[str, Any]:
    chat = (await c.execute(select(chats).where(chats.c.id == cid))).first()
    if chat is None:
        raise not_found("chat")
    msgs = (await c.execute(select(chat_messages).where(chat_messages.c.chat_id == cid)
                            .order_by(chat_messages.c.created_at, chat_messages.c.role.desc()))).all()  # fmt: skip
    acts = (await c.execute(select(chat_actions, plants.c.nickname, species.c.german)
                            .outerjoin(plants, plants.c.id == chat_actions.c.payload["plant_id"].astext)
                            .outerjoin(species, species.c.id == plants.c.species_id)
                            .where(chat_actions.c.message_id.in_([m.id for m in msgs]))
                            .order_by(chat_actions.c.created_at))).all()  # fmt: skip
    plant = None
    if chat.plant_id:
        p = (await c.execute(select(plants.c.id, plants.c.nickname, species.c.german)
                             .join(species, species.c.id == plants.c.species_id)
                             .where(plants.c.id == chat.plant_id))).first()  # fmt: skip
        if p is not None:
            plant = {"id": p.id, "name": p.nickname or (p.german[0] if p.german else p.id)}
    return {
        "id": chat.id, "title": chat.title, "plant": plant,
        "messages": [
            {"id": m.id, "role": m.role, "text": m.text, "status": m.status, "error": m.error, "photos": m.photos,
             "actions": [{"id": a.id, "kind": a.kind, "payload": a.payload, "status": a.status,
                          "plant": a.nickname or (a.german[0] if a.german else None)}
                         for a in acts if a.message_id == m.id]}
            for m in msgs
        ],
    }  # fmt: skip


@router.delete("/chats/{cid}", status_code=204)
async def delete_chat(cid: str, c: Conn) -> Response:
    if (await c.execute(delete(chats).where(chats.c.id == cid))).rowcount == 0:
        raise not_found("chat")
    return Response(status_code=204)


@router.get("/chats/{cid}/stream")
async def stream_answer(cid: str, message_id: str, request: Request) -> StreamingResponse:
    """Server-sent events: `text` with the whole answer so far whenever it grew, then `done`."""
    engine = get_engine(request)

    async def events() -> AsyncIterator[str]:
        sent = None
        loop = asyncio.get_running_loop()
        end = loop.time() + STREAM_MAX_S
        last_sent = loop.time()
        while loop.time() < end:
            async with engine.connect() as c:
                q = select(chat_messages.c.text, chat_messages.c.status, chat_messages.c.error).where(
                    chat_messages.c.id == message_id, chat_messages.c.chat_id == cid
                )
                m = (await c.execute(q)).first()
            if m is None:
                yield 'event: done\ndata: {"status": "missing"}\n\n'
                return
            if m.text != sent:
                sent, last_sent = m.text, loop.time()
                yield f"event: text\ndata: {json.dumps({'text': m.text})}\n\n"
            if m.status in ("done", "failed"):
                yield f"event: done\ndata: {json.dumps({'status': m.status, 'error': m.error})}\n\n"
                return
            if await request.is_disconnected():
                return
            if loop.time() - last_sent > PING_S:  # proxies close silent connections (tool calls can take a while)
                yield ": ping\n\n"
                last_sent = loop.time()
            await asyncio.sleep(STREAM_POLL_S)
        yield 'event: done\ndata: {"status": "timeout"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})  # fmt: skip


async def _decide(c: AsyncConnection, aid: str) -> Any:
    a = (await c.execute(select(chat_actions).where(chat_actions.c.id == aid).with_for_update())).first()
    if a is None:
        raise not_found("action")
    if a.status != "proposed":
        raise ApiError(409, "already decided")
    if datetime.now(UTC) - a.created_at > PROPOSAL_DAYS:
        raise ApiError(409, "proposal expired")
    return a


async def _question_photos(c: AsyncConnection, answer_id: str) -> list[str]:
    """The photos Claude saw for an answer: the newest user message before it that has photos
    (a text-only follow-up to "Blattunterseite?" keeps the earlier ones, as in the worker)."""
    answer = (await c.execute(select(chat_messages).where(chat_messages.c.id == answer_id))).one()
    q = await c.execute(
        select(chat_messages.c.photos)
        .where(chat_messages.c.chat_id == answer.chat_id, chat_messages.c.role == "user",
               chat_messages.c.created_at < answer.created_at,
               func.jsonb_array_length(chat_messages.c.photos) > 0)
        .order_by(chat_messages.c.created_at.desc()).limit(1)
    )  # fmt: skip
    return list(q.scalar() or [])


@router.post("/chat-actions/{aid}/confirm")
async def confirm(aid: str, c: Conn) -> dict[str, Any]:
    a = await _decide(c, aid)
    today = datetime.now(TZ).date()
    plant_id = a.payload.get("plant_id")
    if plant_id and not await active_plant(c, plant_id):
        raise ApiError(409, "plant archived or deleted")
    if a.kind == "aufgabe":
        checked = check_task(a.payload, today, await indoor_plant(c, plant_id))  # the same rules, checked again
        if isinstance(checked, str):
            raise ApiError(409, checked)
        task = await create_task(checked, c, today)
        await c.execute(update(tasks).where(tasks.c.id == task.id).values(source="chat"))
        result = task.id
    elif a.kind == "diagnose":
        result = uuid.uuid4().hex
        await c.execute(diagnoses.insert().values(
            id=result, plant_id=plant_id, title=a.payload["title"], confidence=a.payload["confidence"],
            cause=a.payload["cause"], photo_ids=await _question_photos(c, a.message_id), message_id=a.message_id,
            created_at=datetime.now(UTC),
        ))  # fmt: skip
    else:
        row = (
            await c.execute(select(plants.c.notes).where(plants.c.id == a.payload["plant_id"]).with_for_update())
        ).first()
        if row is None:
            raise not_found("plant")
        line = f"{today.strftime('%d.%m.%Y')}: {a.payload['text']}"
        notes = f"{row.notes}\n{line}".strip() if row.notes else line
        if len(notes) > NOTES_MAX:
            raise ApiError(409, "plant notes are full")
        await c.execute(update(plants).where(plants.c.id == a.payload["plant_id"]).values(notes=notes))
        result = a.payload["plant_id"]
    await c.execute(update(chat_actions).where(chat_actions.c.id == aid)
                    .values(status="done", result_id=result, decided_at=datetime.now(UTC)))  # fmt: skip
    return {"id": aid, "status": "done", "result_id": result}


@router.post("/chat-actions/{aid}/reject")
async def reject(aid: str, c: Conn) -> dict[str, Any]:
    await _decide(c, aid)
    await c.execute(update(chat_actions).where(chat_actions.c.id == aid)
                    .values(status="rejected", decided_at=datetime.now(UTC)))  # fmt: skip
    return {"id": aid, "status": "rejected"}
