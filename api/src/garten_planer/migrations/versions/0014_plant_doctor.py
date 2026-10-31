"""Plant doctor (M9): photos, diagnoses, photos/plant in the chat.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("plant_id", sa.Text, sa.ForeignKey("plants.id", ondelete="SET NULL", name=op.f("fk_chats_plant_id"))),
    )
    op.add_column("chat_messages", sa.Column("photos", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.drop_constraint(op.f("ck_chat_actions_kind"), "chat_actions", type_="check")
    op.create_check_constraint(op.f("ck_chat_actions_kind"), "chat_actions", "kind IN ('aufgabe', 'notiz', 'diagnose')")
    op.create_table(
        "photos",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column(
            "message_id",
            sa.Text,
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL", name=op.f("fk_photos_message_id")),
        ),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index(op.f("ix_photos_message_id"), "photos", ["message_id"])
    op.create_table(
        "diagnoses",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "plant_id",
            sa.Text,
            sa.ForeignKey("plants.id", ondelete="RESTRICT", name=op.f("fk_diagnoses_plant_id")),
            nullable=False,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("confidence", sa.Text, nullable=False),
        sa.Column("cause", sa.Text, nullable=False),
        sa.Column("photo_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "message_id",
            sa.Text,
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL", name=op.f("fk_diagnoses_message_id")),
        ),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("confidence IN ('ziemlich sicher', 'sicher')", name=op.f("ck_diagnoses_confidence")),
    )
    op.create_index(op.f("ix_diagnoses_plant_id"), "diagnoses", ["plant_id"])
    op.execute("GRANT SELECT ON diagnoses TO garten_mcp")  # the history tool reads them (no photos table)


def downgrade() -> None:
    op.drop_table("diagnoses")
    op.drop_table("photos")
    op.execute("DELETE FROM chat_actions WHERE kind = 'diagnose'")
    op.drop_constraint(op.f("ck_chat_actions_kind"), "chat_actions", type_="check")
    op.create_check_constraint(op.f("ck_chat_actions_kind"), "chat_actions", "kind IN ('aufgabe', 'notiz')")
    op.drop_column("chat_messages", "photos")
    op.drop_column("chats", "plant_id")
