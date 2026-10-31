"""GET /api/weather (M6, F-WX-6): current Home Assistant values, the next days'
forecast and staleness. InfluxDB down, not set up or answering oddly means "not
available", never a 500: the rest of the app works without weather (N-16)."""

import asyncio
import logging
from datetime import datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request

from garten_planer.influx import Influx, InfluxError
from garten_planer.routes.todos import TZ
from garten_planer.weather import FETCHED_SQL, HA_SQL, fc_sql, summarise

router = APIRouter()
log = logging.getLogger(__name__)


def get_influx(request: Request) -> Influx | None:
    db: Influx | None = request.app.state.influx
    return db


@router.get("/weather")
async def weather(db: Annotated[Influx | None, Depends(get_influx)]) -> dict[str, Any]:
    if db is None:
        return {"available": False}
    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        ha_rows, fc_rows, fetched = await asyncio.gather(
            db.query(HA_SQL), db.query(fc_sql(midnight)), db.query(FETCHED_SQL)
        )
        return {"available": True, **summarise(ha_rows, fc_rows, now, fetched)}
    except (httpx.HTTPError, InfluxError, ValueError, KeyError, TypeError) as e:
        log.warning("weather failed: %s", type(e).__name__)
        return {"available": False}
