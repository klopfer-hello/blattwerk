"""Weather pipeline (M6a): line protocol + InfluxDB HTTP client, DWD MOSMIX parsing
(public DWD sample, shortened and changed, see the fixture's header) and the weather
summary for the app."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from garten_planer import mosmix
from garten_planer.influx import Influx, InfluxError, line
from garten_planer.weather import summarise

TZ = ZoneInfo("Europe/Berlin")
SAMPLE = (Path(__file__).parent / "fixtures" / "mosmix_sample.kml").read_bytes()
CATALOG = """ID    ICAO NAME                 LAT    LON     ELEV
----- ---- -------------------- -----  ------- -----
10147 EDDH HAMBURG-FUHLSBUETTEL  53.38    9.59    14
10046 ---- KIEL-HOLTENAU         54.23   10.08    27
X1234 ---- BEISPIELDORF          53.00    9.30    10
<bad> ---- KAPUTT                53.00    9.00    10
"""


# ----- line protocol / client -----------------------------------------------------------


def test_line_protocol_escapes_tags_and_skips_missing_fields() -> None:
    ts = datetime(2026, 11, 1, 6, tzinfo=UTC)
    got = line("ha", {"kind": "soil", "label": "Garten (3)"}, {"value": 59.0, "other": None}, ts)
    assert got == rf"ha,kind=soil,label=Garten\ (3) value=59.0 {int(ts.timestamp())}"


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def influx(handler) -> Influx:  # type: ignore[no-untyped-def]
    return Influx("http://influx:8181", "t0ken", "garten", transport=httpx.MockTransport(handler))


def test_query_sends_sql_with_token_and_returns_rows() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json=[{"kind": "outdoor", "value": 6.1}])

    assert run(influx(handler).query("SELECT 1")) == [{"kind": "outdoor", "value": 6.1}]
    assert seen[0].headers["authorization"] == "Bearer t0ken"
    assert seen[0].url.params["db"] == "garten" and seen[0].url.params["q"] == "SELECT 1"


def test_query_of_a_table_that_does_not_exist_yet_is_empty() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="error: table 'ha' not found")

    assert run(influx(handler).query("SELECT * FROM ha")) == []


def test_errors_never_carry_the_token() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(InfluxError) as e:
        run(influx(handler).write(["x v=1 1"]))
    assert "t0ken" not in str(e.value)


def test_database_exists_already_is_fine() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        assert json.loads(r.content) == {"db": "garten", "retention_period": "730d"}
        return httpx.Response(409, text="already exists")

    run(influx(handler).ensure_database("730d"))


# ----- MOSMIX ------------------------------------------------------------------------------


def test_catalog_uses_degrees_and_minutes_and_finds_the_nearest_station() -> None:
    stations = mosmix.parse_catalog(CATALOG)
    assert stations[0] == mosmix.Station("10147", "HAMBURG-FUHLSBUETTEL", pytest.approx(53 + 38 / 60),
                                         pytest.approx(9 + 59 / 60))  # fmt: skip
    assert [s.id for s in stations] == ["10147", "10046", "X1234"]  # "<bad>" never reaches a URL
    assert mosmix.nearest(stations, 54.4, 10.1).id == "10046"
    assert [s.id for s in mosmix.by_distance(stations, 53.0, 9.4)] == ["X1234", "10147", "10046"]


def test_kml_is_parsed_into_hourly_points_in_metric_units() -> None:
    station, points = mosmix.parse_kml(SAMPLE)
    assert station == "10147" and len(points) == 30
    assert points[0].time.tzinfo is not None
    assert points[0].t_air == pytest.approx(8.6)
    assert points[10].t_air == pytest.approx(-5.0)  # the frost night in the sample
    assert points[0].gust_kmh == pytest.approx(12.96)
    assert points[0].precip == 0.0 and points[0].t_min is None  # "-" = not given for this hour


def test_points_become_weather_fc_lines() -> None:
    _, points = mosmix.parse_kml(SAMPLE)
    lines = mosmix.lines("10147", points, fetched=1793500000.0)
    assert len(lines) == 30 and lines[0].startswith("weather_fc,source=dwd,station=10147 ")
    assert "t_air=8.6" in lines[0] and "gust=12.96" in lines[0] and "fetched=1793500000.0" in lines[0]


def test_xml_with_entities_is_refused() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    with pytest.raises(Exception, match=r"(?i)entit"):
        mosmix.parse_kml(bomb)


def test_kmz_content_is_read_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("x.kml", b"0" * 2000)
    monkeypatch.setattr(mosmix, "MAX_KML", 1000)
    with pytest.raises(ValueError, match="too large"):
        mosmix.read_kmz(buf.getvalue())


# ----- summary -----------------------------------------------------------------------------

NOW = datetime(2026, 11, 1, 9, tzinfo=TZ)


def ha(kind: str, value: float, minutes_ago: int, label: str | None = None) -> dict[str, object]:
    t = (NOW - timedelta(minutes=minutes_ago)).astimezone(UTC).replace(tzinfo=None).isoformat()
    return {"time": t, "kind": kind, "label": label, "value": value}


def fc(source: str, hours: int, t_air: float, **kw: float) -> dict[str, object]:
    t = (NOW + timedelta(hours=hours)).astimezone(UTC).replace(tzinfo=None).isoformat()
    return {"time": t, "source": source, "t_air": t_air, **kw}


def test_current_values_take_the_newest_per_sensor() -> None:
    rows = [
        ha("outdoor", 5.0, 30),
        ha("outdoor", 6.1, 5),
        ha("soil", 59, 5, "Gewächshaus"),
        ha("soil", 78, 5, "Vorgarten"),
    ]
    s = summarise(rows, [], NOW)
    assert s["current"]["outdoor"]["value"] == 6.1 and s["current"]["outdoor"]["stale"] is False
    assert [x["label"] for x in s["current"]["soil"]] == ["Gewächshaus", "Vorgarten"]
    assert s["stale"]["sensors"] is None


def test_sensors_older_than_two_hours_are_stale() -> None:
    s = summarise([ha("outdoor", 6.1, 180)], [], NOW)
    assert s["stale"]["sensors"].startswith("2026-11-01T06:00") and s["current"]["outdoor"]["value"] == 6.1


def test_one_dead_sensor_is_marked_even_when_others_report() -> None:
    s = summarise([ha("outdoor", 6.1, 5), ha("greenhouse", 9.0, 300)], [], NOW)
    assert s["stale"]["sensors"] is None and s["current"]["greenhouse"]["stale"] is True


def test_no_sensor_rows_at_all_is_unknown() -> None:
    assert summarise([], [], NOW)["stale"]["sensors"] == "unbekannt"


def test_days_prefer_dwd_and_show_frost_nights() -> None:
    rows = [fc("dwd", h, t, gust=20.0, precip=0.5, t_ground=t - 1) for h, t in [(3, 4.0), (16, -3.0), (20, -1.0)]]
    rows += [fc("openmeteo", 16, 1.0, gust=10.0, precip=0.0)]
    s = summarise([], rows, NOW, [{"source": "dwd", "fetched": (NOW - timedelta(hours=1)).timestamp()}])
    day2 = s["days"][1]
    assert day2["date"] == "2026-11-02" and day2["source"] == "dwd"
    assert day2["t_min"] == -3.0 and day2["frost"] is True and day2["ground_min"] == -4.0
    assert s["stale"]["forecast"] is None


def test_old_forecast_is_stale_even_with_future_rows() -> None:
    fetched = [{"source": "dwd", "fetched": (NOW - timedelta(hours=30)).timestamp()}]
    s = summarise([], [fc("dwd", 16, 2.0)], NOW, fetched)
    assert s["days"] and s["stale"]["forecast"].startswith("2026-10-31T03:00")


def test_day_without_rain_values_shows_no_rain_amount() -> None:
    assert summarise([], [fc("dwd", 16, 2.0)], NOW)["days"][-1]["precip"] is None


def test_open_meteo_fills_in_when_dwd_is_missing() -> None:
    s = summarise([], [fc("openmeteo", 16, 2.0, gust=30.0, precip=1.0)], NOW)
    assert s["days"][-1]["source"] == "openmeteo" and s["days"][-1]["frost"] is False


def test_no_forecast_is_stale() -> None:
    assert summarise([], [], NOW)["stale"]["forecast"] == "unbekannt"


def test_forecast_query_starts_at_local_midnight() -> None:
    from garten_planer.weather import fc_sql

    sql = fc_sql(datetime(2026, 11, 1, 0, 0, tzinfo=TZ))
    assert "time >= '2026-10-31T23:00:00'" in sql and "INTERVAL '3 days'" in sql


def test_empty_coordinates_mean_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from garten_planer.config import Config

    monkeypatch.setenv("GP_LAT", "")
    assert Config().lat is None


def test_influx_repr_hides_the_token() -> None:
    assert "t0ken" not in repr(Influx("http://x", "t0ken"))


# ----- route ------------------------------------------------------------------------------


class FakeInflux:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def query(self, sql: str) -> list[dict[str, object]]:
        if self.fail:
            raise httpx.ConnectError("down")
        if "FROM ha" in sql:
            return [{"time": datetime.now(UTC).replace(tzinfo=None).isoformat(), "kind": "outdoor", "label": None,
                     "value": 6.1}]  # fmt: skip
        return []


def test_weather_route(client) -> None:  # type: ignore[no-untyped-def]
    from garten_planer.routes.weather import get_influx

    client.app.dependency_overrides[get_influx] = lambda: FakeInflux()
    w = client.get("/api/weather").json()
    assert w["available"] is True and w["current"]["outdoor"]["value"] == 6.1 and w["stale"]["forecast"] == "unbekannt"
    client.app.dependency_overrides[get_influx] = lambda: FakeInflux(fail=True)
    assert client.get("/api/weather").json() == {"available": False, "alerts": []}
    client.app.dependency_overrides[get_influx] = lambda: None
    assert client.get("/api/weather").json() == {"available": False, "alerts": []}


# ----- ticket 031: fetch paths, DST, init retry --------------------------------------------------------


def _kmz() -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("MOSMIX_L.kml", SAMPLE)
    return buf.getvalue()


def test_fetch_takes_the_next_station_when_the_nearest_has_no_forecast() -> None:
    written: list[str] = []

    def dwd(r: httpx.Request) -> httpx.Response:
        if "X1234" in r.url.path:
            return httpx.Response(404)
        return httpx.Response(200, content=_kmz())

    def influx_handler(r: httpx.Request) -> httpx.Response:
        written.extend(r.content.decode().splitlines())
        return httpx.Response(204)

    stations = [mosmix.Station("X1234", "NAH", 53.0, 9.4), mosmix.Station("10147", "WEITER", 53.6, 10.0)]
    station, hours = run(mosmix.fetch(influx(influx_handler), stations, transport=httpx.MockTransport(dwd)))
    assert station.id == "10147" and hours == 30 and len(written) == 30


def test_catalog_download_finds_the_nearest() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CATALOG)

    got = run(mosmix.stations_near(54.4, 10.1, transport=httpx.MockTransport(handler)))
    assert got[0].id == "10046"


def test_days_are_local_days_across_the_dst_change() -> None:
    now = datetime(2026, 10, 25, 1, tzinfo=TZ)  # the night the clocks go back (03:00 -> 02:00)
    rows = [{"time": (now.astimezone(UTC) + timedelta(hours=h)).replace(tzinfo=None).isoformat(), "source": "dwd",
             "t_air": float(h)} for h in range(0, 30)]  # fmt: skip
    days = summarise([], rows, now, [{"source": "dwd", "fetched": now.timestamp()}])["days"]
    assert [d["date"] for d in days] == ["2026-10-25", "2026-10-26"]
    assert days[0]["t_max"] == 23.0  # 25 hours that day: 01:00 local + 23 h is still the 25th


def test_influx_init_retries_until_the_database_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    from garten_planer import influx as influx_mod

    calls = {"n": 0}

    async def flaky(self: Influx, retention: str = "730d") -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("starting")

    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setenv("GP_INFLUX_TOKEN", "t")
    monkeypatch.setattr(influx_mod.Influx, "ensure_database", flaky)
    monkeypatch.setattr(influx_mod.asyncio, "sleep", no_sleep)
    assert run(influx_mod._init()) == 0 and calls["n"] == 3
