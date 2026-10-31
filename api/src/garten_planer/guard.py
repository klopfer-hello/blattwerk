"""Write guard (ASGI middleware) for every non-safe method: same-origin only
(Origin / Sec-Fetch-Site), JSON bodies only, at most MAX_BODY bytes. Reads stay
open: no CORS headers are sent, so other sites cannot read the answers anyway."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_BODY = 64 * 1024
PHOTO_PATH = "/api/photos"  # the one route with an image body (plant doctor, M9); checked again there
PHOTO_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_PHOTO = 8 * 1024 * 1024


def refusal(headers: Headers, photo: bool = False) -> tuple[int, str] | None:
    site = headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return 403, "cross-site request refused"
    origin = headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != headers.get("host", ""):
        return 403, "foreign origin refused"
    length = headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > (MAX_PHOTO if photo else MAX_BODY):
        return 413, "request body too large"
    ctype = headers.get("content-type")
    has_body = (length is not None and length != "0") or "transfer-encoding" in headers
    allowed = PHOTO_TYPES if photo else {"application/json"}
    if has_body and (ctype is None or ctype.split(";")[0].strip().lower() not in allowed):
        return 415, "only application/json is accepted" if not photo else "only JPEG, PNG or WebP photos"
    return None


class WriteGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        photo = scope["method"] == "POST" and scope.get("path") == PHOTO_PATH
        limit = MAX_PHOTO if photo else MAX_BODY
        refused = refusal(Headers(scope=scope), photo)
        if refused is not None:
            await JSONResponse({"error": refused[1]}, status_code=refused[0])(scope, receive, send)
            return
        # Read the whole body first (bodies are small JSON), so chunked uploads
        # without Content-Length hit the same limit, then replay it to the app.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > limit:
                await JSONResponse({"error": "request body too large"}, status_code=413)(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
