"""Database access: one async PyMongo client per app (opened in the lifespan),
handlers get the database through `get_db`."""

from typing import Any, cast

from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from garten_planer.config import Config

type Db = AsyncDatabase[dict[str, Any]]


def connect(cfg: Config) -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient(
        cfg.mongo_url.get_secret_value(),
        serverSelectionTimeoutMS=cfg.db_timeout_ms,
        appname="garten-planer",
        tz_aware=True,
    )


def get_db(request: Request) -> Db:
    return cast(Db, request.app.state.db)
