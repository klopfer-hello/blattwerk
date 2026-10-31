"""Every write must be same-origin, JSON and small (security rules: no CSRF
from other sites, no form posts, no huge bodies)."""

from collections.abc import Iterator

from fastapi.testclient import TestClient

from garten_planer.config import Config
from garten_planer.main import create_app
from tests.conftest import BASE
from tests.test_settings import VALID


def test_foreign_origin_is_refused(client: TestClient) -> None:
    r = client.put("/api/settings", json=VALID, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_cross_site_fetch_metadata_is_refused(client: TestClient) -> None:
    r = client.put("/api/settings", json=VALID, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_and_no_origin_are_allowed(client: TestClient) -> None:
    assert client.put("/api/settings", json=VALID, headers={"Origin": BASE}).status_code == 200
    assert client.put("/api/settings", json=VALID, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.put("/api/settings", json=VALID).status_code == 200  # curl/scripts on the LAN


def test_non_json_write_is_refused(client: TestClient) -> None:
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    r = client.put("/api/settings", content=b"location=x", headers=form)
    assert r.status_code == 415


def test_oversized_body_is_refused(client: TestClient) -> None:
    r = client.put("/api/settings", content=b"{" + b" " * 70_000 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_reads_are_not_guarded(client: TestClient) -> None:
    assert client.get("/api/settings", headers={"Origin": "https://evil.example"}).status_code == 200


def test_origin_with_port_matches_host_with_port(config: Config) -> None:
    with TestClient(create_app(config), base_url="http://localhost:8080") as c:
        r = c.put("/api/settings", json=VALID, headers={"Origin": "http://localhost:8080"})
    assert r.status_code == 200


def test_oversized_chunked_body_is_refused(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"{"
        for _ in range(80):
            yield b" " * 1024
        yield b"}"

    r = client.put("/api/settings", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
