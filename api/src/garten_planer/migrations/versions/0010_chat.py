"""Garden chat (M8): chats, messages, proposed actions.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "chat_id",
            sa.Text,
            sa.ForeignKey("chats.id", ondelete="CASCADE", name=op.f("fk_chat_messages_chat_id")),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("model", sa.Text),
        sa.Column("cost_usd", sa.Float),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_chat_messages_role")),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_chat_messages_status")),
    )
    op.create_index(op.f("ix_chat_messages_chat_id"), "chat_messages", ["chat_id"])
    op.create_index(op.f("ix_chat_messages_status_created_at"), "chat_messages", ["status", "created_at"])
    op.create_table(
        "chat_actions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "message_id",
            sa.Text,
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE", name=op.f("fk_chat_actions_message_id")),
            nullable=False,
        ),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("result_id", sa.Text),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("decided_at", TS),
        sa.CheckConstraint("kind IN ('aufgabe', 'notiz')", name=op.f("ck_chat_actions_kind")),
        sa.CheckConstraint("status IN ('proposed', 'done', 'rejected')", name=op.f("ck_chat_actions_status")),
    )
    op.create_index(op.f("ix_chat_actions_message_id"), "chat_actions", ["message_id"])


def downgrade() -> None:
    op.drop_table("chat_actions")
    op.drop_table("chat_messages")
    op.drop_table("chats")
