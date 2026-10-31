"""Phenology (M7): phase entry dates per year and source, long-term normals.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "pheno_events",
        sa.Column("year", sa.Integer, primary_key=True),
        sa.Column("phase", sa.Text, primary_key=True),
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("reports", sa.Integer, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("source IN ('dwd', 'garten')", name=op.f("ck_pheno_events_source")),
    )
    op.create_table(
        "pheno_normals",
        sa.Column("phase", sa.Text, primary_key=True),
        sa.Column("doy", sa.Integer, nullable=False),
        sa.Column("stations", sa.Integer, nullable=False),
        sa.Column("computed_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pheno_normals")
    op.drop_table("pheno_events")
