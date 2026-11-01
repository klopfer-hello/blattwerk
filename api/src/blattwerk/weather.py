"""Weather summary for the app (M6, F-WX-6, N-16): newest Home Assistant value per
sensor (each with its own age), and per local day min/max temperature, ground
minimum, rain, gusts and frost from the forecast (DWD first, Open-Meteo where DWD
has nothing). Every forecast row carries `fetched` (when it was downloaded), so an
old forecast is reported as old even though its rows still lie in the future.
Pure: rows in, dict out; the route does the queries."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

SENSORS_STALE = timedelta(hours=2)  # Telegraf polls every 5 min
FORECAST_STALE = timedelta(hours=8)  # DWD every hour, MOSMIX_L issued every 6 h
DAYS = 3
SOURCES = ("dwd", "openmeteo")  # preference order
UNKNOWN = "unbekannt"  # stale, and no value within the query window

# SELECT *: a column appears only once something wrote it (no "label" before the first soil value)
HA_SQL = "SELECT * FROM ha WHERE time > now() - INTERVAL '1 day' ORDER BY time"
# The forecast hours just ahead are rewritten by every fetch: their `fetched` is the newest one.
# Queries stay narrow in time: InfluxDB 3 Core refuses to scan more than a few hundred files.
FETCHED_SQL = (
    "SELECT source, max(fetched) AS fetched FROM weather_fc "
    "WHERE time >= now() - INTERVAL '1 hour' AND time < now() + INTERVAL '6 hours' GROUP BY source"
)


def fc_sql(since: datetime) -> str:
    """Forecast rows from local midnight (a whole "today"), for DAYS days; `since` is our own value."""
    start = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    # only a formatted datetime and a constant go into the text (the HTTP API takes no bind parameters here)
    return (
        f"SELECT * FROM weather_fc WHERE time >= '{start}' "  # noqa: S608
        f"AND time < TIMESTAMP '{start}' + INTERVAL '{DAYS} days' ORDER BY time"
    )


def _time(v: Any) -> datetime:
    t = datetime.fromisoformat(str(v))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def _current(ha_rows: list[dict[str, Any]], now: datetime) -> tuple[dict[str, Any], str | None]:
    tz = now.tzinfo
    newest: dict[tuple[str, str], tuple[float, datetime]] = {}
    for r in ha_rows:
        if r.get("value") is not None and r.get("kind"):
            newest[(str(r["kind"]), str(r.get("label") or ""))] = (float(r["value"]), _time(r["time"]))
    current: dict[str, Any] = {"soil": []}
    for (kind, label), (value, at) in sorted(newest.items()):
        item = {"value": _round(value), "at": at.astimezone(tz).isoformat(), "stale": now - at >= SENSORS_STALE}
        if kind == "soil":
            current["soil"].append({"label": label, **item})
        else:
            current[kind] = item
    last = max((at for _, at in newest.values()), default=None)
    stale = UNKNOWN if last is None else None if now - last < SENSORS_STALE else last.astimezone(tz).isoformat()
    return current, stale


def _days(fc_rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in fc_rows:
        d = _time(r["time"]).astimezone(now.tzinfo).date()
        if now.date() <= d < now.date() + timedelta(days=DAYS):
            by_day[d.isoformat()][str(r.get("source"))].append(r)
    days = []
    for day in sorted(by_day):
        source = next((s for s in SOURCES if by_day[day].get(s)), None)
        if source is None:
            continue
        rows = by_day[day][source]

        def vals(field: str, rows: list[dict[str, Any]] = rows) -> list[float]:
            return [float(r[field]) for r in rows if r.get(field) is not None]

        t, ground, rain = vals("t_air"), vals("t_ground"), vals("precip")
        t_min, g_min = min(t, default=None), min(ground, default=None)
        days.append({
            "date": day, "source": source, "t_min": _round(t_min), "t_max": _round(max(t, default=None)),
            "ground_min": _round(g_min), "precip": _round(sum(rain)) if rain else None,
            "gust_max": _round(max(vals("gust"), default=None)),
            "frost": (t_min is not None and t_min <= 0) or (g_min is not None and g_min <= 0),
        })  # fmt: skip
    return days


def summarise(
    ha_rows: list[dict[str, Any]],
    fc_rows: list[dict[str, Any]],
    now: datetime,
    fetched: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current, sensors_stale = _current(ha_rows, now)
    days = _days(fc_rows, now)
    last_fetch = max(
        (datetime.fromtimestamp(float(r["fetched"]), UTC) for r in fetched or [] if r.get("fetched") is not None),
        default=None,
    )
    if not days or last_fetch is None:
        forecast_stale: str | None = UNKNOWN
    elif now - last_fetch < FORECAST_STALE:
        forecast_stale = None
    else:
        forecast_stale = last_fetch.astimezone(now.tzinfo).isoformat()
    return {"current": current, "days": days, "stale": {"sensors": sensors_stale, "forecast": forecast_stale}}
