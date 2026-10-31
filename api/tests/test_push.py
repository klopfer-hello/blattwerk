"""Push (F-TD-6): digest settings, device subscriptions (only real push services:
no SSRF through user-supplied URLs), test message via the outbox, digest timing."""

import base64
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from garten_planer.digest import digest_due, digest_text
from tests.conftest import BASE

H = {"Origin": BASE}
TZ = ZoneInfo("Europe/Berlin")
FCM = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {"p256dh": "B" + "A" * 86, "auth": "A" * 22}


def sub(endpoint: str = FCM, **kw: Any) -> dict[str, Any]:
    return {"endpoint": endpoint, "keys": KEYS, "label": "Handy", **kw}


@pytest.mark.parametrize(
    "endpoint",
    [
        FCM,
        "https://web.push.apple.com/QGuQyavXutnMrCN8ldd",
        "https://updates.push.services.mozilla.com/wpush/v2/gAAAA",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
    ],
)
def test_known_push_services_are_accepted(client: TestClient, endpoint: str) -> None:
    assert client.post("/api/push/subscriptions", json=sub(endpoint), headers=H).status_code == 201


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",  # not https
        "https://evil.example/fcm.googleapis.com",
        "https://fcm.googleapis.com.evil.example/x",
        "https://garten-planer-db:5432/x",  # internal host (SSRF)
        "https://user" + "@" + "fcm.googleapis.com/x",  # userinfo in a URL (built in parts: not an address)
        "https://fcm.googleapis.com:8443/x",
        "https://notpush.apple.com/x",
        # review M3b: parsers disagree on these (urllib3 ends the host at the backslash)
        "https://evil.example\\.push.apple.com/x",
        "https://evil.example%5C.push.apple.com/x",
        "https://evil.example%2F.push.apple.com/x",
        "https://evil.example/.push.apple.com/x",
        "https://fcm.googleapis.com" + "\\" + "@evil.example/x",
        "https://f\u0441m.googleapis.com/x",  # Cyrillic es instead of Latin c
        "https://[::1]/x",
    ],
)
def test_other_urls_are_refused(client: TestClient, endpoint: str) -> None:
    r = client.post("/api/push/subscriptions", json=sub(endpoint), headers=H)
    assert r.status_code == 422 and "endpoint" in r.json()["fields"]


def test_subscribe_is_an_upsert_and_unsubscribe_is_idempotent(client: TestClient, db: Engine) -> None:
    assert client.post("/api/push/subscriptions", json=sub(), headers=H).status_code == 201
    assert client.post("/api/push/subscriptions", json=sub(label="Neu"), headers=H).status_code == 200
    with db.connect() as c:
        assert c.execute(text("SELECT count(*), max(label) FROM push_subs")).one() == (1, "Neu")
    for _ in range(2):
        assert client.post("/api/push/unsubscribe", json={"endpoint": FCM}, headers=H).status_code == 204
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM push_subs")).scalar() == 0


@pytest.mark.parametrize("keys", [{"p256dh": "short", "auth": "A" * 22}, {"p256dh": "B" + "A" * 86, "auth": "x!"}, {}])
def test_keys_are_checked(client: TestClient, keys: dict[str, str]) -> None:
    assert client.post("/api/push/subscriptions", json=sub(keys=keys), headers=H).status_code == 422


def test_test_message_goes_to_the_outbox(client: TestClient, db: Engine) -> None:
    client.post("/api/push/subscriptions", json=sub(), headers=H)
    assert client.post("/api/push/test", json={"endpoint": FCM}, headers=H).status_code == 202
    with db.connect() as c:
        assert c.execute(text("SELECT title FROM push_messages WHERE sent_at IS NULL")).scalars().all() == [
            "Test vom Garten-Planer"
        ]
    assert client.post("/api/push/test", json={"endpoint": FCM + "x"}, headers=H).status_code == 404


def test_public_key_is_served(client: TestClient) -> None:
    assert client.get("/api/push/key").json() == {"public_key": "test-public-key"}


def test_digest_settings_are_validated(client: TestClient) -> None:
    base = client.get("/api/settings").json()
    assert base["notifications"] == {
        "weather_push": True,
        "digest_mode": "daily",
        "digest_time": "08:00",
        "digest_weekday": 5,
    }
    for bad in ({"digest_time": "8:00"}, {"digest_time": "24:00"}, {"digest_mode": "hourly"}, {"digest_weekday": 7}):
        body = {**base, "notifications": {**base["notifications"], **bad}}
        assert client.put("/api/settings", json=body, headers=H).status_code == 422


# ----- digest timing (pure) ---------------------------------------------------

AT_7 = datetime(2026, 11, 7, 7, 59, tzinfo=TZ)  # a Saturday
AT_8 = datetime(2026, 11, 7, 8, 0, tzinfo=TZ)


@pytest.mark.parametrize(
    ("at", "mode", "weekday", "last", "expected"),
    [
        (AT_7, "daily", 5, None, False),  # before the time
        (AT_8, "daily", 5, None, True),
        (AT_8, "daily", 5, date(2026, 11, 7), False),  # already sent today
        (AT_8, "daily", 5, date(2026, 11, 6), True),
        (AT_8, "weekly", 5, None, True),  # Saturday
        (AT_8, "weekly", 0, None, False),  # only on Mondays
        (AT_8, "off", 5, None, False),
    ],
)
def test_digest_due(at: datetime, mode: str, weekday: int, last: date | None, expected: bool) -> None:
    assert digest_due(at, mode, "08:00", weekday, last) is expected


@pytest.mark.parametrize(
    ("titles", "expected"),
    [
        (["Leimring prüfen"], ("Neue Aufgabe im Garten", "Leimring prüfen")),
        (["A", "B"], ("2 neue Aufgaben im Garten", "A und B")),
        (["A", "B", "C", "D", "E"], ("5 neue Aufgaben im Garten", "A, B, C und 2 weitere")),
    ],
)
def test_digest_text(titles: list[str], expected: tuple[str, str]) -> None:
    assert digest_text(titles) == expected


def test_keygen_output_works_with_pywebpush() -> None:
    from py_vapid import Vapid

    from garten_planer.push import keygen

    public, private = keygen()
    vapid = Vapid.from_string(private)
    raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert base64.urlsafe_b64encode(raw).rstrip(b"=").decode() == public


def test_number_of_devices_is_capped(client: TestClient) -> None:
    for i in range(20):
        assert client.post("/api/push/subscriptions", json=sub(f"{FCM}-{i}"), headers=H).status_code == 201
    assert client.post("/api/push/subscriptions", json=sub(f"{FCM}-21"), headers=H).status_code == 409
    assert client.post("/api/push/subscriptions", json=sub(f"{FCM}-3"), headers=H).status_code == 200  # update ok
