"""Push: count 401/403 answers per device (ticket 021).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("push_subs", sa.Column("auth_failures", sa.Integer, nullable=False, server_default="0"))
    op.add_column("push_subs", sa.Column("auth_failed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("push_subs", "auth_failed_at")
    op.drop_column("push_subs", "auth_failures")
