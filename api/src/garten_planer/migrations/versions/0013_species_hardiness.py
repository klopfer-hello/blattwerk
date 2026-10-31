"""Frost hardiness per species (ticket 032, F-WX-5). Seed values arrive with the seed upsert.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("species", sa.Column("hardiness_c", sa.SmallInteger))


def downgrade() -> None:
    op.drop_column("species", "hardiness_c")
