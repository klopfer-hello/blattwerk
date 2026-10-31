"""Health for the deploy script and Docker: version plus a DB ping. 503 when the
database does not answer, so a broken switch is noticed and rolled back."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from garten_planer.db import get_db

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    try:
        await get_db(request).command("ping")
        db = "ok"
    except PyMongoError:
        db = "error"
    body = {"status": "ok" if db == "ok" else "error", "version": request.app.state.config.version, "db": db}
    return JSONResponse(body, status_code=200 if db == "ok" else 503, headers={"Cache-Control": "no-store"})
