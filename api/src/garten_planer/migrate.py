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


if __name__ == "__main__":
    upgrade(Config().database_url.get_secret_value())
    print("migrations: at head")
