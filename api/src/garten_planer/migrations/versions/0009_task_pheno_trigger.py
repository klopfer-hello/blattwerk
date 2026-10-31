"""Season-driven tasks (M7b): phenological trigger on tasks.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("pheno_phase", sa.Text))
    op.add_column("tasks", sa.Column("pheno_offset", sa.SmallInteger, nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("pheno_window", sa.SmallInteger, nullable=False, server_default="14"))


def downgrade() -> None:
    op.drop_column("tasks", "pheno_window")
    op.drop_column("tasks", "pheno_offset")
    op.drop_column("tasks", "pheno_phase")
