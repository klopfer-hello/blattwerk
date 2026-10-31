"""Alembic environment: online migrations only, URL from migrate.alembic_config."""

from alembic import context
from sqlalchemy import create_engine

from garten_planer.schema import metadata

url = context.config.attributes["url"]
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
