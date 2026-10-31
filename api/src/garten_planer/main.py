"""App factory: `uvicorn --factory garten_planer.main:create_app` (config from
the environment) or `create_app(Config(...))` in tests."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from garten_planer.config import Config
from garten_planer.db import connect
from garten_planer.guard import WriteGuard
from garten_planer.routes import health, settings

log = logging.getLogger("garten_planer")


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = connect(cfg)
        app.state.db = client[cfg.db_name]
        try:
            yield
        finally:
            await client.close()

    app = FastAPI(
        title="Garten-Planer API",
        version=cfg.version,
        lifespan=lifespan,
        docs_url=None,  # Swagger UI loads from a CDN, which the strict CSP blocks; schema below
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.config = cfg
    app.add_middleware(WriteGuard)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {".".join(str(p) for p in e["loc"][1:]): e["msg"] for e in exc.errors()}
        return JSONResponse({"error": "invalid input", "fields": fields}, status_code=422)

    @app.exception_handler(PyMongoError)
    async def db_down(_: Request, exc: PyMongoError) -> JSONResponse:
        log.warning("database error: %s", type(exc).__name__)  # type only: messages can contain hosts
        return JSONResponse({"error": "database unavailable"}, status_code=503)

    app.include_router(health.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    return app
