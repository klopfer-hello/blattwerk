"""Standorte (F-ST-2): unique names (case-insensitive), delete only when empty."""

from fastapi.testclient import TestClient

from tests.conftest import BASE

H = {"Origin": BASE}
BEET = {"name": "Beet am Haus", "light": "halbschattig", "type": "beet", "notes": ""}


def new(client: TestClient, **kw: object) -> dict[str, object]:
    r = client.post("/api/standorte", json={**BEET, **kw}, headers=H)
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_create_list_update(client: TestClient) -> None:
    s = new(client, name="  Beet am Haus ")
    assert s["name"] == "Beet am Haus" and s["plant_count"] == 0
    new(client, name="Gewächshaus", light="sonnig", type="gewaechshaus")
    assert [x["name"] for x in client.get("/api/standorte").json()] == ["Beet am Haus", "Gewächshaus"]
    r = client.put(f"/api/standorte/{s['id']}", json={**BEET, "light": "schattig"}, headers=H)
    assert r.status_code == 200 and r.json()["light"] == "schattig"


def test_duplicate_name_is_409_case_insensitive(client: TestClient) -> None:
    a = new(client)
    assert client.post("/api/standorte", json={**BEET, "name": "BEET AM HAUS"}, headers=H).status_code == 409
    b = new(client, name="Zaun Süd")
    assert client.put(f"/api/standorte/{b['id']}", json={**BEET, "name": "beet am haus"}, headers=H).status_code == 409
    assert client.put(f"/api/standorte/{a['id']}", json={**BEET, "name": "Beet am HAUS"}, headers=H).status_code == 200


def test_validation(client: TestClient) -> None:
    for bad in ({"name": ""}, {"name": "x" * 61}, {"light": "dunkel"}, {"type": "balkon"}, {"notes": "x" * 501}):
        assert client.post("/api/standorte", json={**BEET, **bad}, headers=H).status_code == 422


def test_unknown_id_is_404(client: TestClient) -> None:
    assert client.put("/api/standorte/nope", json=BEET, headers=H).status_code == 404
    assert client.delete("/api/standorte/nope", headers=H).status_code == 404


def test_delete_only_when_empty(client: TestClient) -> None:
    s = new(client)
    plant = {"species_id": "dahlia", "standort_id": s["id"]}
    p = client.post("/api/plants", json=plant, headers=H).json()
    assert client.delete(f"/api/standorte/{s['id']}", headers=H).status_code == 409
    client.post(f"/api/plants/{p['id']}/archive", headers=H)
    assert client.delete(f"/api/standorte/{s['id']}", headers=H).status_code == 409  # archived plants keep history
    empty = new(client, name="Leer")
    assert client.delete(f"/api/standorte/{empty['id']}", headers=H).status_code == 204
    assert all(x["id"] != empty["id"] for x in client.get("/api/standorte").json())
