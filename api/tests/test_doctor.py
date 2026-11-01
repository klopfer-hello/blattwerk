"""Plant doctor (M9): photo upload (verified, re-encoded without metadata), photos and plant
context in the chat, images to Claude, diagnosis proposals and the plant's history."""

import asyncio
import io
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from blattwerk import blattwerk_tools as gt
from blattwerk.worker import run_chat_jobs
from tests.conftest import BASE, DATABASE_URL

H = {"Origin": BASE}
RESULT = {"type": "result", "is_error": False, "total_cost_usd": 0.02, "modelUsage": {"claude-test": {}}}


def jpeg(w: int = 2400, h: int = 1800, gps: bool = True) -> bytes:
    img = Image.new("RGB", (w, h), (70, 140, 60))
    exif = Image.Exif()
    exif[0x010F] = "Kamera-Hersteller"  # Make
    if gps:
        exif[0x8825] = {1: "N", 2: (51.0, 3.0, 0.0), 3: "E", 4: (13.0, 44.0, 0.0)}  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def upload(client: TestClient, data: bytes, ctype: str = "image/jpeg", headers: dict[str, str] | None = None) -> Any:
    return client.post("/api/photos", content=data, headers={**H, "Content-Type": ctype, **(headers or {})})


def plant(client: TestClient) -> str:
    st = client.post("/api/standorte", json={"name": "Beet", "light": "sonnig", "type": "beet"}, headers=H).json()
    r = client.post("/api/plants", json={"species_id": "malus-domestica", "standort_id": st["id"], "nickname": "Topaz"},
                    headers=H)  # fmt: skip
    return str(r.json()["id"])


# ----- upload -----------------------------------------------------------------------------------


def test_upload_strips_metadata_and_shrinks(client: TestClient) -> None:
    r = upload(client, jpeg())
    assert r.status_code == 201, r.text
    got = client.get(f"/api/photos/{r.json()['id']}")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(got.content))
    assert max(img.size) == 1600 and not img.getexif()


@pytest.mark.parametrize(
    ("data", "ctype", "status"),
    [(b"not an image at all", "image/jpeg", 422), (b"%PDF-1.4", "application/pdf", 415), (b"x", "text/plain", 415)],
)
def test_only_real_images_are_taken(client: TestClient, data: bytes, ctype: str, status: int) -> None:
    assert upload(client, data, ctype).status_code == status


def test_too_large_and_foreign_uploads_are_refused(client: TestClient) -> None:
    assert upload(client, b"0" * (9 * 1024 * 1024)).status_code == 413
    assert upload(client, jpeg(64, 64), headers={"Origin": "https://evil.example"}).status_code == 403


def test_decompression_bomb_is_refused(client: TestClient) -> None:
    img = Image.new("1", (12000, 12000))  # tiny file, 144 megapixels
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert upload(client, buf.getvalue(), "image/png").status_code == 422


# ----- chat with photos --------------------------------------------------------------------------


def fake(seen: list[tuple[str, list[bytes]]]) -> Any:
    async def stream(prompt: str, system: str, message_id: str, images: list[bytes]) -> AsyncGenerator[dict[str, Any]]:
        seen.append((prompt, images))
        yield {"type": "stream_event", "event": {"type": "content_block_delta",
               "delta": {"type": "text_delta", "text": "Das sieht nach Mehltau aus."}}}  # fmt: skip
        yield RESULT

    return stream


def work(stream: Any) -> int:
    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_chat_jobs(engine, stream, daily_limit=150)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_photos_and_plant_go_to_claude_with_the_question(client: TestClient) -> None:
    pid = plant(client)
    ids = [upload(client, jpeg(800, 600)).json()["id"] for _ in range(2)]
    r = client.post("/api/chats", json={"text": "Weiße Flecken?", "photo_ids": ids, "plant_id": pid}, headers=H)
    assert r.status_code == 201, r.text
    seen: list[tuple[str, list[bytes]]] = []
    work(fake(seen))
    prompt, images = seen[0]
    assert len(images) == 2 and images[0][:2] == b"\xff\xd8" and "Topaz" in prompt and pid in prompt
    chat = client.get(f"/api/chats/{r.json()['chat_id']}").json()
    assert chat["plant"]["id"] == pid and chat["messages"][0]["photos"] == ids


def test_a_text_follow_up_keeps_the_photos(client: TestClient) -> None:
    """Claude asks back ("Seit wann?"), the user answers in text: the photos still go along and
    a diagnosis then saved keeps them."""
    pid = plant(client)
    ids = [upload(client, jpeg(640, 480)).json()["id"]]
    chat = client.post("/api/chats", json={"text": "Flecken?", "photo_ids": ids, "plant_id": pid}, headers=H).json()
    seen: list[tuple[str, list[bytes]]] = []
    work(fake(seen))
    follow = client.post(f"/api/chats/{chat['chat_id']}/messages", json={"text": "Seit einer Woche."}, headers=H).json()
    work(fake(seen))
    assert len(seen[1][1]) == 1 and "[Foto]" in seen[1][0]
    call(gt.diagnose_vorschlagen, follow["message_id"], pid, "Schorf", "sicher", "")
    aid = client.get(f"/api/chats/{chat['chat_id']}").json()["messages"][3]["actions"][0]["id"]
    client.post(f"/api/chat-actions/{aid}/confirm", headers=H)
    assert client.get(f"/api/plants/{pid}/history").json()[0]["photos"] == ids


def test_unsent_uploads_are_limited(client: TestClient, db: Engine) -> None:
    from blattwerk.routes.photos import MAX_UNSENT

    first = upload(client, jpeg(64, 64)).json()["id"]
    with db.begin() as c:
        c.execute(text("INSERT INTO photos (id, data, width, height, created_at) "
                       "SELECT md5(g::text), data, width, height, now() FROM photos, generate_series(2, :n) g"),
                  {"n": MAX_UNSENT})  # fmt: skip
    assert upload(client, jpeg(64, 64)).status_code == 429
    client.post("/api/chats", json={"text": "x", "photo_ids": [first]}, headers=H)  # a sent photo frees a slot
    assert upload(client, jpeg(64, 64)).status_code == 201


@pytest.mark.parametrize("case", ["unknown", "too many", "used twice"])
def test_photo_ids_must_be_fresh_own_uploads(client: TestClient, case: str) -> None:
    ids = [upload(client, jpeg(64, 64)).json()["id"] for _ in range(4)]
    if case == "unknown":
        body = {"text": "x", "photo_ids": ["nope"]}
    elif case == "too many":
        body = {"text": "x", "photo_ids": ids}
    else:
        client.post("/api/chats", json={"text": "erst", "photo_ids": ids[:1]}, headers=H)
        body = {"text": "x", "photo_ids": ids[:1]}
    assert client.post("/api/chats", json=body, headers=H).status_code == 422


def test_unsent_uploads_are_purged(client: TestClient, db: Engine) -> None:
    from blattwerk.routes.photos import purge_photos

    upload(client, jpeg(64, 64))
    with db.begin() as c:
        c.execute(text("UPDATE photos SET created_at = now() - interval '2 days'"))

    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await purge_photos(engine)
        finally:
            await engine.dispose()

    assert asyncio.run(go()) == 1


# ----- diagnosis -----------------------------------------------------------------------------------


def call(fn: Any, *args: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(DATABASE_URL)
        try:
            async with engine.begin() as c:
                return await fn(c, *args)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_diagnosis_is_proposed_saved_and_in_the_history(client: TestClient, db: Engine) -> None:
    pid = plant(client)
    ids = [upload(client, jpeg(640, 480)).json()["id"]]
    chat = client.post("/api/chats", json={"text": "Was ist das?", "photo_ids": ids, "plant_id": pid}, headers=H).json()
    r = call(gt.diagnose_vorschlagen, chat["message_id"], pid, "Echter Mehltau", "ziemlich sicher", "feuchte Woche")
    assert r["vorgeschlagen"] is True
    aid = client.get(f"/api/chats/{chat['chat_id']}").json()["messages"][1]["actions"][0]["id"]
    assert client.post(f"/api/chat-actions/{aid}/confirm", headers=H).status_code == 200
    hist = client.get(f"/api/plants/{pid}/history").json()
    d = hist[0]
    assert d["kind"] == "diagnose" and d["title"] == "Echter Mehltau" and d["photos"] == ids
    assert d["confidence"] == "ziemlich sicher"
    tools_view = call(gt.verlauf, pid)
    assert tools_view["diagnosen"][0]["befund"] == "Echter Mehltau"


@pytest.mark.parametrize("confidence", ["absolut", ""])
def test_diagnosis_needs_a_known_confidence(client: TestClient, db: Engine, confidence: str) -> None:
    pid = plant(client)
    chat = client.post("/api/chats", json={"text": "x"}, headers=H).json()
    assert "fehler" in call(gt.diagnose_vorschlagen, chat["message_id"], pid, "Mehltau", confidence, "")


def test_history_has_done_todos_too(client: TestClient) -> None:
    pid = plant(client)
    soon = date.today().isoformat()  # this month: /todos/heute lists the current month
    client.post("/api/tasks", json={"title": "Leimring", "category": "pflanzenschutz", "recurrence": "once",
                                    "due_date": soon, "plant_id": pid}, headers=H)  # fmt: skip
    tid = next(t for t in client.get("/api/todos/heute").json()["open"] if t["task"]["title"] == "Leimring")["id"]
    client.post(f"/api/todos/{tid}/done", json={"note": "Erledigt."}, headers=H)
    hist = client.get(f"/api/plants/{pid}/history").json()
    assert [(h["kind"], h["title"], h["note"]) for h in hist] == [("aufgabe", "Leimring", "Erledigt.")]
