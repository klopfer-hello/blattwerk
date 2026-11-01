"""Database access: one async SQLAlchemy engine per app (psycopg 3), created in
the lifespan. Handlers get a connection with `Depends(conn)`: one transaction
per request, committed when the handler returns, rolled back on any error."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from blattwerk.config import Config


def make_engine(cfg: Config) -> AsyncEngine:
    return create_async_engine(
        cfg.database_url.get_secret_value(),
        pool_size=5,
        pool_pre_ping=True,
        connect_args={"connect_timeout": cfg.db_timeout_s},
    )


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


async def conn(request: Request) -> AsyncIterator[AsyncConnection]:
    async with get_engine(request).begin() as c:
        yield c


# scope="function": commit BEFORE the response is sent (the default "request" scope
# would commit afterwards: the client could see 201 and then not find the row).
Conn = Annotated[AsyncConnection, Depends(conn, scope="function")]
