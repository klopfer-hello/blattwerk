"""Run the Alembic migrations: `python -m garten_planer.migrate` (the one-shot
`migrate` service in compose, before the api starts). The scripts ship inside
the package, so the runtime image needs no alembic.ini. Uses GP_DATABASE_URL."""

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from garten_planer.config import Config


def alembic_config(url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["url"] = url  # not via set_main_option: keeps the password out of the ini interpolation
    return cfg


def upgrade(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def set_mcp_password(url: str, password: str) -> None:
    """Let the chat tools' role log in with the password from the host .env (every deploy,
    so a changed password takes effect). The statement is built with psycopg's literal
    quoting: ALTER ROLE takes no bind parameters."""
    from psycopg import sql
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        with engine.begin() as c:
            stmt = sql.SQL("ALTER ROLE garten_mcp LOGIN PASSWORD {}").format(sql.Literal(password))
            raw = stmt.as_string(c.connection.dbapi_connection)  # type: ignore[arg-type]
            c.exec_driver_sql(raw.replace("%", "%%"))  # the driver reads % as a placeholder
    finally:
        engine.dispose()


if __name__ == "__main__":
    cfg = Config()
    upgrade(cfg.database_url.get_secret_value())
    print("migrations: at head")
    if pw := cfg.mcp_db_password.get_secret_value():
        set_mcp_password(cfg.database_url.get_secret_value(), pw)
        print("chat role: password set")
