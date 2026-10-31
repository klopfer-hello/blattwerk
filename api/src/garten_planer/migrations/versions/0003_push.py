"""Push digest (M3b): device subscriptions, outbox, job state, todos.notified_at.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("todos", sa.Column("notified_at", TS))
    op.create_table(
        "push_subs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("p256dh", sa.Text, nullable=False),
        sa.Column("auth", sa.Text, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_ok_at", TS),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subs_endpoint")),
    )
    op.create_table(
        "push_messages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "sub_id",
            sa.Text,
            sa.ForeignKey("push_subs.id", ondelete="CASCADE", name=op.f("fk_push_messages_sub_id")),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("sent_at", TS),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("last_error", sa.Text),
    )
    op.create_index(op.f("ix_push_messages_sub_id"), "push_messages", ["sub_id"])
    op.create_table(
        "kv",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", JSONB, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("kv")
    op.drop_table("push_messages")
    op.drop_table("push_subs")
    op.drop_column("todos", "notified_at")
