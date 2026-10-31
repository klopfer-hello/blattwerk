"""Fixtures: every test gets the app on its own throwaway database in the
real FerretDB of the test compose project (MONGO_URL), dropped afterwards."""

import os
import time
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from garten_planer.config import Config
from garten_planer.main import create_app

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://test:test@localhost:27017/")
BASE = "http://testserver"


@pytest.fixture(scope="session", autouse=True)
def _database_ready() -> None:
    """FerretDB starts after PostgreSQL; wait up to 60 s for the first ping."""
    deadline = time.monotonic() + 60
    while True:
        try:
            with MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000) as c:
                c.admin.command("ping")
            return
        except PyMongoError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


@pytest.fixture
def config() -> Iterator[Config]:
    cfg = Config(mongo_url=MONGO_URL, db_name=f"test_{uuid.uuid4().hex[:12]}", version="9.9.9+test")
    yield cfg
    with MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000) as c:
        c.drop_database(cfg.db_name)


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url=BASE) as c:
        yield c
