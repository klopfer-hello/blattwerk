"""Photos for the plant doctor (M9). The only upload: a raw image body (the write guard lets
exactly this route through, up to MAX_UPLOAD). Pillow checks it is a real image of a known
format, refuses decompression bombs, and stores a fresh JPEG without any metadata (EXIF,
GPS, camera), at most MAX_SIDE pixels. Photos leave the server only to Claude, for the answer
they belong to. Unsent uploads and photos of deleted chats go, unless a saved diagnosis uses
them."""

import io
import uuid
import warnings
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from blattwerk.db import Conn
from blattwerk.errors import ApiError, not_found
from blattwerk.schema import diagnoses, photos

router = APIRouter()
MAX_UPLOAD = 8 * 1024 * 1024
MAX_SIDE = 1600
MAX_PIXELS = 40_000_000  # a 48 MP phone photo is fine after the client shrank it; bombs are not
FORMATS = {"JPEG", "PNG", "WEBP"}
CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
UNSENT_KEEP = timedelta(days=1)
MAX_UNSENT = 50  # unsent uploads per day: a stuck client or script cannot fill the disk


def clean(data: bytes) -> tuple[bytes, int, int]:
    """A verified image as a fresh JPEG without metadata (ValueError when it is none)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # Pillow only warns up to 2x its limit
            probe = Image.open(io.BytesIO(data), formats=sorted(FORMATS))  # no other Pillow parser sees the bytes
        with probe:
            if probe.format not in FORMATS:
                raise ValueError("format")
            if probe.width * probe.height > MAX_PIXELS:
                raise ValueError("too many pixels")
            probe.verify()
        with Image.open(io.BytesIO(data), formats=sorted(FORMATS)) as src:
            src.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG: decode at a reduced scale (less memory and time)
            img = src.convert("RGB")  # drops alpha, palette and all metadata blocks
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85, optimize=True)  # no exif= argument: nothing carried over
        return out.getvalue(), img.width, img.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            SyntaxError) as e:  # fmt: skip
        raise ValueError("not an image") from e


@router.post("/photos", status_code=201)
async def upload_photo(request: Request, c: Conn) -> dict[str, Any]:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype not in CONTENT_TYPES:
        raise ApiError(415, "only JPEG, PNG or WebP photos")
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, "photo too large")
    unsent = await c.execute(select(func.count()).select_from(photos).where(
        photos.c.message_id.is_(None), photos.c.created_at > datetime.now(UTC) - UNSENT_KEEP))  # fmt: skip
    if unsent.scalar_one() >= MAX_UNSENT:
        raise ApiError(429, "too many unsent photos")
    try:
        jpeg, w, h = await run_in_threadpool(clean, data)
    except ValueError:
        raise ApiError(422, "not a usable photo", {"photo": "invalid"}) from None
    pid = uuid.uuid4().hex
    await c.execute(insert(photos).values(id=pid, data=jpeg, width=w, height=h, created_at=datetime.now(UTC)))
    return {"id": pid, "width": w, "height": h}


@router.get("/photos/{pid}")
async def read_photo(pid: str, c: Conn) -> Response:
    data = (await c.execute(select(photos.c.data).where(photos.c.id == pid))).scalar()
    if data is None:
        raise not_found("photo")
    return Response(content=bytes(data), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400, immutable"})  # fmt: skip


async def purge_photos(engine: AsyncEngine) -> int:
    """Photos no message and no saved diagnosis uses, older than a day."""
    async with engine.begin() as c:
        used = select(func.jsonb_array_elements_text(diagnoses.c.photo_ids))
        gone = await c.execute(
            delete(photos).where(
                photos.c.message_id.is_(None),
                photos.c.created_at < datetime.now(UTC) - UNSENT_KEEP,
                photos.c.id.not_in(used),
            )
        )
        return int(gone.rowcount or 0)
