"""AI name suggestions (M5): name jobs.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "name_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("candidates", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model", sa.Text),
        sa.Column("cost_usd", sa.Float),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_name_jobs_status")),
    )
    op.create_index(op.f("ix_name_jobs_status_created_at"), "name_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("name_jobs")
