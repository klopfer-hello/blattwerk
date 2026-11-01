"""Database-level guarantees: the Alembic migrations produce exactly the schema
in schema.py (no drift in tables, columns or constraint names the code relies
on), writes are committed before the answer, and unexpected DB errors become
JSON without user data in it."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError, OperationalError

from blattwerk.main import db_error_response
from blattwerk.schema import metadata
from tests.conftest import BASE

H = {"Origin": BASE}

SHAPE = text("""
    SELECT 'col:' || table_name || '.' || column_name || ':' || data_type || ':' || is_nullable
      FROM information_schema.columns WHERE table_schema = :s AND table_name <> 'alembic_version'
    UNION ALL
    SELECT 'con:' || c.conname || ':' || c.contype::text
      FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
     WHERE n.nspname = :s AND c.conrelid::regclass::text NOT LIKE '%alembic_version'
    UNION ALL
    SELECT 'idx:' || indexname FROM pg_indexes WHERE schemaname = :s AND tablename <> 'alembic_version'
""")


@pytest.fixture
def expected_schema(engine: Engine) -> Iterator[str]:
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS expected CASCADE; CREATE SCHEMA expected"))
        metadata.create_all(c.execution_options(schema_translate_map={None: "expected"}))
    yield "expected"
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA expected CASCADE"))


def test_migrations_match_schema_py(engine: Engine, expected_schema: str) -> None:
    with engine.connect() as c:
        migrated = {r[0] for r in c.execute(SHAPE, {"s": "public"})}
        expected = {r[0] for r in c.execute(SHAPE, {"s": expected_schema})}
    assert migrated == expected, {"only in migrations": migrated - expected, "only in schema.py": expected - migrated}


def test_write_is_committed_before_the_answer(client: TestClient, db: Engine) -> None:
    r = client.post("/api/standorte", json={"name": "Beet", "light": "sonnig", "type": "beet"}, headers=H)
    assert r.status_code == 201
    with db.connect() as c:  # a separate connection sees the row right away
        assert c.execute(text("SELECT count(*) FROM standorte")).scalar() == 1


@pytest.mark.parametrize(
    ("exc", "status", "error"),
    [
        (IntegrityError("INSERT …", {"notes": "Geheimnis"}, Exception("fk")), 409, "conflict"),
        (DataError("INSERT …", {"notes": "Geheimnis"}, Exception("too long")), 422, "invalid data"),
        (OperationalError("SELECT 1", {}, Exception("down")), 503, "database unavailable"),
    ],
)
def test_db_errors_map_to_json_without_user_data(exc: DBAPIError, status: int, error: str) -> None:
    r = db_error_response(exc)
    assert r.status_code == status
    assert json.loads(r.body) == {"error": error}
