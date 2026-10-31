"""DWD MOSMIX_L point forecast (M6): nearest station, KMZ download, KML parsing.

Telegraf cannot unpack the KMZ (zip), so the worker fetches it hourly and writes
`weather_fc` (source=dwd) to InfluxDB in metric units: °C (from K), km/h (from
m/s), mm. Only fixed DWD URLs are fetched; the station comes from DWD's own
catalog (LAT/LON there are degrees.minutes)."""

import io
import math
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime

import httpx
from defusedxml import ElementTree as ET  # no entity expansion, no external entities

from garten_planer.influx import Influx, line

CATALOG_URL = "https://www.dwd.de/DE/leistungen/met_verfahren_mosmix/mosmix_stationskatalog.cfg?view=nasPublication"
KMZ_URL = (
    "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/single_stations/{id}/kml/MOSMIX_L_LATEST_{id}.kmz"
)
NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "dwd": "https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd",
}
MAX_KMZ = 5_000_000  # a single station is ~20 kB; anything huge is not what we asked for
MAX_KML = 20_000_000
MAX_CATALOG = 2_000_000
STATION_ID = re.compile(r"[A-Z0-9]{4,5}")  # goes into a URL: only what DWD ids look like


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Point:
    time: datetime
    t_air: float | None  # °C, 2 m
    t_ground: float | None  # °C, 5 cm above ground (ground frost)
    t_min: float | None  # °C, minimum of the last 12 h (only some hours)
    gust_kmh: float | None  # max gust within the last hour
    precip: float | None  # mm in the last hour


def _degmin(v: str) -> float:
    x = float(v)
    deg = math.trunc(x)
    return deg + (x - deg) * 100 / 60


def parse_catalog(text: str) -> list[Station]:
    out = []
    for row in text.splitlines()[2:]:
        if len(row) < 46 or not row[:5].strip():
            continue
        sid = row[:5].strip()
        if not STATION_ID.fullmatch(sid):
            continue
        try:
            out.append(Station(sid, row[11:32].strip(), _degmin(row[32:38]), _degmin(row[38:46])))
        except ValueError:
            continue
    return out


def by_distance(stations: list[Station], lat: float, lon: float) -> list[Station]:
    def dist(s: Station) -> float:  # equirectangular is plenty for "nearest within Germany"
        x = math.radians(s.lon - lon) * math.cos(math.radians((s.lat + lat) / 2))
        return math.hypot(x, math.radians(s.lat - lat))

    return sorted(stations, key=dist)


def nearest(stations: list[Station], lat: float, lon: float) -> Station:
    return by_distance(stations, lat, lon)[0]


def _values(raw: str, convert: float = 0.0, factor: float = 1.0) -> list[float | None]:
    return [None if v == "-" else round(float(v) * factor + convert, 2) for v in raw.split()]


def parse_kml(data: bytes) -> tuple[str, list[Point]]:
    root = ET.fromstring(data)
    times = [datetime.fromisoformat(t.text or "") for t in root.iterfind(".//dwd:ForecastTimeSteps/dwd:TimeStep", NS)]
    placemark = root.find(".//kml:Placemark", NS)
    if placemark is None or not times:
        raise ValueError("no forecast in KML")
    station = (placemark.findtext("kml:name", "", NS)).strip()
    series = {
        f.get(f"{{{NS['dwd']}}}elementName"): f.findtext("dwd:value", "", NS)
        for f in placemark.iterfind(".//dwd:Forecast", NS)
    }
    kelvin = -273.15
    cols = {
        "t_air": _values(series.get("TTT", ""), kelvin),
        "t_ground": _values(series.get("T5cm", ""), kelvin),
        "t_min": _values(series.get("TN", ""), kelvin),
        "gust_kmh": _values(series.get("FX1", ""), factor=3.6),
        "precip": _values(series.get("RR1c", "")),
    }

    def at(name: str, i: int) -> float | None:
        col = cols[name]
        return col[i] if i < len(col) else None

    points = [
        Point(t, *(at(n, i) for n in ("t_air", "t_ground", "t_min", "gust_kmh", "precip"))) for i, t in enumerate(times)
    ]
    return station, points


def lines(station: str, points: list[Point], fetched: float | None = None) -> list[str]:
    """`fetched` (unix seconds) on every row: the api tells an old forecast from a fresh one."""
    stamp = fetched if fetched is not None else time.time()
    return [
        line("weather_fc", {"source": "dwd", "station": station},
             {"t_air": p.t_air, "t_ground": p.t_ground, "t_min": p.t_min, "gust": p.gust_kmh,
              "precip": p.precip, "fetched": stamp}, p.time)
        for p in points
    ]  # fmt: skip


def read_kmz(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z, z.open(z.namelist()[0]) as f:
        kml = f.read(MAX_KML + 1)  # bounded, whatever the zip header claims
    if len(kml) > MAX_KML:
        raise ValueError("KML too large")
    return kml


def _client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=False, transport=transport)


async def stations_near(
    lat: float, lon: float, count: int = 3, transport: httpx.AsyncBaseTransport | None = None
) -> list[Station]:
    """The nearest few: a station in the catalog may have no MOSMIX_L file (404), then the next one is used."""
    async with _client(transport) as c:
        r = await c.get(CATALOG_URL)
        r.raise_for_status()
    if len(r.content) > MAX_CATALOG:
        raise ValueError("catalog too large")
    return by_distance(parse_catalog(r.text), lat, lon)[:count]


async def fetch(
    influx: Influx, stations: list[Station], transport: httpx.AsyncBaseTransport | None = None
) -> tuple[Station, int]:
    """Latest forecast of the first station that has one; returns it and the number of hours written."""
    async with _client(transport) as c:
        for station in stations:
            r = await c.get(KMZ_URL.format(id=station.id))
            if r.status_code == 404:
                continue
            r.raise_for_status()
            if len(r.content) > MAX_KMZ:
                raise ValueError("KMZ too large")
            sid, points = parse_kml(read_kmz(r.content))
            await influx.write(lines(sid, points))
            return station, len(points)
    raise ValueError("no MOSMIX forecast for the nearest stations")
