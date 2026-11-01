"""GET /api/weather (M6, F-WX-6): current Home Assistant values, the next days'
forecast and staleness. InfluxDB down, not set up or answering oddly means "not
available", never a 500: the rest of the app works without weather (N-16)."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request

from blattwerk.db import Conn
from blattwerk.influx import Influx, InfluxError
from blattwerk.routes.todos import TZ
from blattwerk.weather import FETCHED_SQL, HA_SQL, fc_sql, summarise
from blattwerk.wetterwacht import active_alerts

router = APIRouter()
log = logging.getLogger(__name__)


def get_influx(request: Request) -> Influx | None:
    db: Influx | None = request.app.state.influx
    return db


@router.get("/weather")
async def weather(db: Annotated[Influx | None, Depends(get_influx)], c: Conn) -> dict[str, Any]:
    now = datetime.now(TZ)
    warnings = await active_alerts(c, now.date())  # from Postgres: shown even when InfluxDB is down
    if db is None:
        return {"available": False, "alerts": warnings}
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        ha_rows, fc_rows, fetched = await asyncio.gather(
            db.query(HA_SQL), db.query(fc_sql(midnight)), db.query(FETCHED_SQL)
        )
        return {"available": True, "alerts": warnings, **summarise(ha_rows, fc_rows, now, fetched)}
    except (httpx.HTTPError, InfluxError, ValueError, KeyError, TypeError) as e:
        log.warning("weather failed: %s", type(e).__name__)
        return {"available": False, "alerts": warnings}


@router.get("/alerts")
async def weather_alerts(c: Conn) -> list[dict[str, Any]]:
    """Active weather alerts only (Postgres): cheap enough for Heute to poll."""
    return await active_alerts(c, datetime.now(TZ).date())
