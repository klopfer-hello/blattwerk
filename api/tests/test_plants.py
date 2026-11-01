"""Plants (F-PL-2/3/5): references checked, never hard-deleted, names expanded."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, update
from sqlalchemy.exc import IntegrityError

from blattwerk.schema import plants, standorte
from tests.conftest import BASE

H = {"Origin": BASE}


@pytest.fixture
def standort(client: TestClient) -> str:
    r = client.post("/api/standorte", json={"name": "Weg", "light": "sonnig", "type": "beet"}, headers=H)
    return str(r.json()["id"])


def plant(standort: str, **kw: object) -> dict[str, Any]:
    return {"species_id": "malus-domestica", "cultivar_id": "malus-domestica:sonate", "standort_id": standort,
            "nickname": "Säulenapfel am Weg", "form": "Säule", "planted_year": 2022, **kw}  # fmt: skip


def test_create_and_read_expanded(client: TestClient, standort: str) -> None:
    r = client.post("/api/plants", json=plant(standort), headers=H)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["species"] == {
        "id": "malus-domestica",
        "latin": "Malus domestica",
        "german": "Apfel",
        "growth": "baum",
        "woody": True,
    }
    assert p["cultivar"] == {"id": "malus-domestica:sonate", "name": "Sonate"}
    assert p["standort"] == {"id": standort, "name": "Weg", "light": "sonnig", "type": "beet", "indoor": False,
                            "windows": []}  # fmt: skip
    assert p["archived"] is False
    assert client.get(f"/api/plants/{p['id']}").json() == p
    assert [x["id"] for x in client.get("/api/plants").json()] == [p["id"]]


def test_update(client: TestClient, standort: str) -> None:
    p = client.post("/api/plants", json=plant(standort), headers=H).json()
    r = client.put(f"/api/plants/{p['id']}", json=plant(standort, nickname="Neu", cultivar_id=None), headers=H)
    assert r.status_code == 200
    assert r.json()["nickname"] == "Neu" and r.json()["cultivar"] is None


def test_archive_and_restore_never_delete(client: TestClient, standort: str) -> None:
    p = client.post("/api/plants", json=plant(standort), headers=H).json()
    assert client.post(f"/api/plants/{p['id']}/archive", headers=H).json()["archived"] is True
    assert client.get("/api/plants").json() == []
    assert [x["id"] for x in client.get("/api/plants", params={"archived": "true"}).json()] == [p["id"]]
    assert client.post(f"/api/plants/{p['id']}/restore", headers=H).json()["archived"] is False
    assert client.delete(f"/api/plants/{p['id']}", headers=H).status_code == 405


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"species_id": "nope"}, "species_id"),
        ({"cultivar_id": "prunus-avium:celeste"}, "cultivar_id"),  # Sorte of another species
        ({"standort_id": "nope"}, "standort_id"),
    ],
)
def test_references_are_checked(client: TestClient, standort: str, change: dict[str, str], field: str) -> None:
    r = client.post("/api/plants", json=plant(standort, **change), headers=H)
    assert r.status_code == 422
    assert field in r.json()["fields"]


@pytest.mark.parametrize(
    "bad",
    [{"planted_year": 1899}, {"planted_year": 2100}, {"girth_cm": 0}, {"girth_cm": 1001}, {"nickname": "x" * 61},
     {"form": "Pyramide"}, {"notes": "x" * 1001}, {"extra": 1}],
)  # fmt: skip
def test_validation(client: TestClient, standort: str, bad: dict[str, object]) -> None:
    assert client.post("/api/plants", json=plant(standort, **bad), headers=H).status_code == 422


def test_unknown_plant_is_404(client: TestClient, standort: str) -> None:
    assert client.get("/api/plants/nope").status_code == 404
    assert client.put("/api/plants/nope", json=plant(standort), headers=H).status_code == 404
    assert client.post("/api/plants/nope/archive", headers=H).status_code == 404


def test_db_refuses_dangling_references(client: TestClient, standort: str, db: Engine) -> None:
    """The DB itself guards what the API checks: no race can leave a plant without its Standort,
    and a plant's Sorte always belongs to its species."""
    p = client.post("/api/plants", json=plant(standort), headers=H).json()
    with pytest.raises(IntegrityError, match="fk_plants_standort_id"), db.begin() as c:
        c.execute(delete(standorte).where(standorte.c.id == standort))
    with pytest.raises(IntegrityError, match="fk_plants_cultivar_of_species"), db.begin() as c:
        c.execute(update(plants).where(plants.c.id == p["id"]).values(cultivar_id="prunus-avium:celeste"))
