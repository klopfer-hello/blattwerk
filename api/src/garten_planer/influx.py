"""InfluxDB 3 Core over its HTTP API (M6): write line protocol, query with SQL.

Plain httpx instead of the Flight client: few rows per request, no pyarrow in the
image. The token goes only into the Authorization header, never into an error.
`python -m garten_planer.influx init` creates the database with its retention
(one-shot service before Telegraf, like `migrate` for Postgres)."""

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from garten_planer.config import Config

DB = "garten"
RETENTION = "730d"  # raw weather data: two years (04-tech-stack.md)


class InfluxError(Exception):
    """Short, safe message (status + reason); details only in the worker log."""


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def line(measurement: str, tags: dict[str, str | None], fields: dict[str, float | None], ts: datetime) -> str:
    """One line of line protocol, seconds precision; empty tags and missing fields are left out."""
    t = ",".join(f"{k}={_escape(v)}" for k, v in sorted(tags.items()) if v)
    f = ",".join(f"{k}={float(v)!r}" for k, v in fields.items() if v is not None)
    return f"{measurement}{',' + t if t else ''} {f} {int(ts.timestamp())}"


@dataclass(frozen=True)
class Influx:
    url: str
    token: str = field(repr=False)  # never in a log line or traceback
    db: str = DB
    transport: httpx.AsyncBaseTransport | None = None  # tests

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=10,
            transport=self.transport,
            follow_redirects=False,
        )

    async def write(self, lines: list[str]) -> None:
        if not lines:
            return
        async with self._client() as c:
            r = await c.post(
                "/api/v3/write_lp", params={"db": self.db, "precision": "second"}, content="\n".join(lines)
            )
        if r.status_code >= 300:
            raise InfluxError(f"write failed: HTTP {r.status_code}")

    async def query(self, sql: str) -> list[dict[str, Any]]:
        async with self._client() as c:
            r = await c.get("/api/v3/query_sql", params={"db": self.db, "q": sql, "format": "json"})
        if r.status_code == 200:
            rows = r.json()
            return rows if isinstance(rows, list) else []
        if "not found" in r.text.lower():  # nothing written yet: table or database missing
            return []
        raise InfluxError(f"query failed: HTTP {r.status_code}")

    async def ensure_database(self, retention: str = RETENTION) -> None:
        async with self._client() as c:
            r = await c.post("/api/v3/configure/database", json={"db": self.db, "retention_period": retention})
        if r.status_code >= 300 and r.status_code != 409:
            raise InfluxError(f"create database failed: HTTP {r.status_code}")


def from_config(cfg: Config) -> Influx | None:
    token = cfg.influx_token.get_secret_value()
    return Influx(cfg.influx_url, token) if token else None


async def _init() -> int:
    db = from_config(Config())
    if db is None:
        print("no GP_INFLUX_TOKEN", file=sys.stderr)
        return 1
    for attempt in range(30):  # influxdb may still be starting
        try:
            await db.ensure_database()
            print(f"database {db.db} ready (retention {RETENTION})")
            return 0
        except (httpx.HTTPError, InfluxError) as e:
            if attempt == 29:
                print(f"influx init failed: {type(e).__name__}", file=sys.stderr)
        await asyncio.sleep(2)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_init()) if sys.argv[1:] == ["init"] else 2)
