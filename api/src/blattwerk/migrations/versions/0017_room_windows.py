"""Window directions belong to the room; the plant keeps the distance (and which window, when
the room has several). User feedback on M11.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("standorte", sa.Column("windows", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.execute(  # what the plants said so far becomes the room's windows
        "UPDATE standorte s SET windows = (SELECT coalesce(jsonb_agg(DISTINCT p.window_dir), '[]'::jsonb)"
        " FROM plants p WHERE p.standort_id = s.id AND p.window_dir IN ('N', 'O', 'S', 'W')) WHERE s.type = 'zimmer'"
    )


def downgrade() -> None:
    op.drop_column("standorte", "windows")
