from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert

from garten_planer.schema import settings
from tests.conftest import BASE

JSON = {"Content-Type": "application/json", "Origin": BASE}

VALID: dict[str, Any] = {
    "location": {"ort": "Musterstadt", "plz": "00000", "bundesland": "Sachsen"},
    "preferences": {"fertiliser": "organisch", "eco_defaults": False},
    "legal": {"baumschutz_girth_cm": 80, "fruit_trees_exempt": True},
    "notifications": {"weather_push": False},
}


def test_defaults_when_nothing_saved(client: TestClient) -> None:
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == {
        "location": {"ort": None, "plz": None, "bundesland": None},
        "preferences": {"fertiliser": "gemischt", "eco_defaults": True},
        "legal": {"baumschutz_girth_cm": None, "fruit_trees_exempt": True},
        "notifications": {"weather_push": True},
    }


def test_put_saves_and_get_returns_it(client: TestClient) -> None:
    r = client.put("/api/settings", json=VALID, headers=JSON)
    assert r.status_code == 200
    assert r.json() == VALID
    assert client.get("/api/settings").json() == VALID


def test_put_trims_ort_and_empty_becomes_none(client: TestClient) -> None:
    body = {**VALID, "location": {"ort": "  Musterstadt ", "plz": None, "bundesland": None}}
    assert client.put("/api/settings", json=body, headers=JSON).json()["location"]["ort"] == "Musterstadt"
    body["location"]["ort"] = "   "
    assert client.put("/api/settings", json=body, headers=JSON).json()["location"]["ort"] is None


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("location", "plz"), "1234"),
        (("location", "plz"), "0123A"),
        (("location", "bundesland"), "Bayernland"),
        (("location", "ort"), "x" * 81),
        (("preferences", "fertiliser"), "chemisch"),
        (("legal", "baumschutz_girth_cm"), 5),
        (("legal", "baumschutz_girth_cm"), 501),
    ],
)
def test_put_rejects_invalid_values(client: TestClient, path: tuple[str, str], value: object) -> None:
    body: dict[str, Any] = {k: dict(v) for k, v in VALID.items()}
    body[path[0]][path[1]] = value
    assert client.put("/api/settings", json=body, headers=JSON).status_code == 422
    assert client.get("/api/settings").json()["location"]["ort"] is None  # nothing stored


def test_put_rejects_unknown_fields(client: TestClient) -> None:
    body = {**VALID, "admin": True}
    assert client.put("/api/settings", json=body, headers=JSON).status_code == 422


def test_stored_document_with_unknown_fields_still_reads(client: TestClient, db: Engine) -> None:
    """After a rollback to an older version, newer fields must not break reading."""
    data = {**VALID, "future": 1, "location": {**VALID["location"], "lat": 50.1}}
    with db.begin() as c:
        c.execute(insert(settings).values(id=1, data=data, schema_version=2))
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json() == VALID
