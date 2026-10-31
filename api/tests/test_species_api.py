"""Species master data in the DB: seeded at start, resolver endpoint, user additions."""

from fastapi.testclient import TestClient

from tests.conftest import BASE

H = {"Origin": BASE}


def test_seed_is_loaded_and_species_has_cultivars(client: TestClient) -> None:
    r = client.get("/api/species/malus-domestica")
    assert r.status_code == 200
    body = r.json()
    assert body["latin"] == "Malus domestica" and body["woody"] is True
    assert "Sonate" in [c["name"] for c in body["cultivars"]]


def test_resolve_endpoint(client: TestClient) -> None:
    r = client.get("/api/species/resolve", params={"q": "Felsenbrine Obelisk"})
    assert r.status_code == 200
    top = r.json()["candidates"][0]
    assert (top["latin"], top["cultivar_name"]) == ("Amelanchier alnifolia", "Obelisk")
    assert client.get("/api/species/resolve", params={"q": ""}).json() == {"candidates": []}
    assert client.get("/api/species/resolve", params={"q": "x" * 201}).status_code == 422


def test_add_cultivar_then_it_resolves(client: TestClient) -> None:
    r = client.post("/api/species/amelanchier-lamarckii/cultivars", json={"name": " Ballerina "}, headers=H)
    assert r.status_code == 201
    assert r.json() == {"id": "amelanchier-lamarckii:ballerina", "name": "Ballerina", "source": "user"}
    # Same Sorte in another spelling: the existing one comes back (200), nothing is lost.
    again = client.post("/api/species/amelanchier-lamarckii/cultivars", json={"name": "BALLERINA"}, headers=H)
    assert (again.status_code, again.json()["id"]) == (200, "amelanchier-lamarckii:ballerina")
    top = client.get("/api/species/resolve", params={"q": "Kupfer-Felsenbirne Ballerina"}).json()["candidates"][0]
    assert top["cultivar_id"] == "amelanchier-lamarckii:ballerina"


def test_add_species(client: TestClient) -> None:
    body = {"latin": "Cornus kousa", "german": ["Japanischer Blumen-Hartriegel"], "growth": "strauch", "woody": True}
    r = client.post("/api/species", json=body, headers=H)
    assert r.status_code == 201 and r.json()["id"] == "cornus-kousa"
    assert client.post("/api/species", json=body, headers=H).status_code == 409
    top = client.get("/api/species/resolve", params={"q": "Blumen-Hartriegel"}).json()["candidates"][0]
    assert top["latin"] == "Cornus kousa"


def test_unknown_species_is_404(client: TestClient) -> None:
    assert client.get("/api/species/nope").status_code == 404
    assert client.post("/api/species/nope/cultivars", json={"name": "X"}, headers=H).status_code == 404


def test_names_that_fold_to_nothing_are_refused(client: TestClient) -> None:
    assert client.post("/api/species/dahlia/cultivars", json={"name": "!!!"}, headers=H).status_code == 422
    body = {"latin": "- - -", "german": ["X"], "growth": "staude", "woody": False}
    assert client.post("/api/species", json=body, headers=H).status_code == 422
