"""Health for the deploy script and Docker: version plus a DB ping. 503 when the
database does not answer, so a broken switch is noticed and rolled back."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from blattwerk.db import get_engine

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    try:
        async with get_engine(request).connect() as c:
            await c.execute(text("SELECT 1"))
        db = "ok"
    except SQLAlchemyError, OSError:
        db = "error"
    body = {"status": "ok" if db == "ok" else "error", "version": request.app.state.config.version, "db": db}
    return JSONResponse(body, status_code=200 if db == "ok" else 503, headers={"Cache-Control": "no-store"})
