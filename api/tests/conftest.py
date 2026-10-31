"""Fixtures. One test database per run, built with the real Alembic migrations
(so every run also tests them); all tables are emptied before each test and
every test gets a fresh app (which seeds the species again)."""

import os
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from garten_planer.config import Config
from garten_planer.main import create_app
from garten_planer.migrate import upgrade

DATABASE_URL = os.environ.get(
    "GP_TEST_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/garten_planer_test"
)
BASE = "http://testserver"
TABLES = (
    "plan_jobs, push_messages, push_subs, kv, todos, tasks, care_plans, plants, standorte, cultivars, species, settings"
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Wait for PostgreSQL (up to 60 s), start from an empty schema, migrate to head."""
    eng = create_engine(DATABASE_URL)
    deadline = time.monotonic() + 60
    while True:
        try:
            with eng.begin() as c:
                c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
            break
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    upgrade(DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Engine:
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {TABLES}"))
    return engine


@pytest.fixture
def config(db: Engine) -> Config:
    return Config(database_url=DATABASE_URL, version="9.9.9+test", vapid_public="test-public-key")  # type: ignore[arg-type]


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url=BASE) as c:
        yield c
