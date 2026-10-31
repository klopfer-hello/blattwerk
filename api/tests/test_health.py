from fastapi.testclient import TestClient

from garten_planer.config import Config
from garten_planer.main import create_app


def test_healthz_reports_version_and_db(client: TestClient) -> None:
    r = client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "9.9.9+test", "db": "ok"}
    assert r.headers["cache-control"] == "no-store"


def test_db_errors_become_503_json_not_500() -> None:
    cfg = Config(mongo_url="mongodb://nobody:x@127.0.0.1:1/", db_name="x", version="1", db_timeout_ms=300)
    with TestClient(create_app(cfg)) as c:
        r = c.get("/api/settings")
        w = c.put("/api/settings", json={}, headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()) == (503, {"error": "database unavailable"})
    assert (w.status_code, w.json()) == (503, {"error": "database unavailable"})


def test_healthz_is_503_when_db_unreachable() -> None:
    cfg = Config(mongo_url="mongodb://nobody:x@127.0.0.1:1/", db_name="x", version="1", db_timeout_ms=300)
    with TestClient(create_app(cfg)) as c:
        r = c.get("/api/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "version": "1", "db": "error"}
