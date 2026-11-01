"""App factory: `uvicorn --factory blattwerk.main:create_app` (config from
the environment) or `create_app(Config(...))` in tests."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError

from blattwerk.config import Config
from blattwerk.db import make_engine
from blattwerk.errors import ApiError
from blattwerk.guard import WriteGuard
from blattwerk.influx import from_config
from blattwerk.routes import (
    chat,
    health,
    names,
    photos,
    plans,
    plants,
    push,
    season,
    settings,
    species,
    standorte,
    todos,
    weather,
)

log = logging.getLogger("blattwerk")


def db_error_response(exc: DBAPIError) -> JSONResponse:
    """Any DB error that a route did not turn into an ApiError. Logs the type only:
    SQLAlchemy messages contain the statement parameters (user data, notes)."""
    log.warning("database error: %s", type(exc.orig).__name__ if exc.orig else type(exc).__name__)
    if isinstance(exc, IntegrityError):  # e.g. a Standort deleted between check and insert
        return JSONResponse({"error": "conflict"}, status_code=409)
    if isinstance(exc, DataError):
        return JSONResponse({"error": "invalid data"}, status_code=422)
    return JSONResponse({"error": "database unavailable"}, status_code=503)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(cfg)
        app.state.seeded = False
        app.state.ready_lock = asyncio.Lock()
        app.state.catalog = None
        app.state.catalog_gen = 0
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(
        title="Blattwerk API",
        version=cfg.version,
        lifespan=lifespan,
        docs_url=None,  # Swagger UI loads from a CDN, which the strict CSP blocks; schema below
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.config = cfg
    app.state.influx = from_config(cfg)
    app.add_middleware(WriteGuard)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
        return JSONResponse({"error": "invalid input", "fields": fields}, status_code=422)

    @app.exception_handler(DBAPIError)
    async def db_error(_: Request, exc: DBAPIError) -> JSONResponse:
        return db_error_response(exc)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        body: dict[str, object] = {"error": exc.message}
        if exc.fields:
            body["fields"] = exc.fields
        return JSONResponse(body, status_code=exc.status)

    routes = (health, settings, standorte, names, species, plants, todos, push, plans, weather, season, chat, photos)
    for module in routes:
        app.include_router(module.router, prefix="/api")
    return app
