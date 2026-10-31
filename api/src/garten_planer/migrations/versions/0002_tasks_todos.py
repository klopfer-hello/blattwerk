"""Tasks and their to-do occurrences (M3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

from garten_planer.schema import TASK_CATEGORY, TASK_SOURCE

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("plant_id", sa.Text, sa.ForeignKey("plants.id", ondelete="RESTRICT", name=op.f("fk_tasks_plant_id"))),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("instructions", sa.Text, nullable=False),
        sa.Column("recurrence", sa.Text, nullable=False),
        sa.Column("due_date", sa.Date),
        sa.Column("month_from", sa.SmallInteger),
        sa.Column("month_to", sa.SmallInteger),
        sa.Column("interval_days", sa.Integer),
        sa.Column("start_date", sa.Date),
        sa.Column("urgent", sa.Boolean, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(_in("category", TASK_CATEGORY), name=op.f("ck_tasks_category")),
        sa.CheckConstraint(_in("source", TASK_SOURCE), name=op.f("ck_tasks_source")),
        sa.CheckConstraint(
            "(recurrence = 'once' AND due_date IS NOT NULL)"
            " OR (recurrence = 'yearly' AND month_from BETWEEN 1 AND 12 AND month_to BETWEEN 1 AND 12)"
            " OR (recurrence = 'interval' AND interval_days > 0)",
            name=op.f("ck_tasks_timing"),
        ),
    )
    op.create_index(op.f("ix_tasks_plant_id"), "tasks", ["plant_id"])
    op.create_table(
        "todos",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "task_id",
            sa.Text,
            sa.ForeignKey("tasks.id", ondelete="RESTRICT", name=op.f("fk_todos_task_id")),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("period", sa.Text, nullable=False),
        sa.Column("due_from", sa.Date, nullable=False),
        sa.Column("due_to", sa.Date, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("done_at", TS),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("postponed", sa.Boolean, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("task_id", "generation", "period", name=op.f("uq_todos_task_period")),
        sa.CheckConstraint(_in("status", ("open", "done", "skipped")), name=op.f("ck_todos_status")),
        sa.CheckConstraint("due_to >= due_from", name=op.f("ck_todos_window")),
        sa.CheckConstraint("(status = 'open') = (done_at IS NULL)", name=op.f("ck_todos_done_at")),
    )
    op.create_index(op.f("ix_todos_status_due_from"), "todos", ["status", "due_from"])
    op.create_index(op.f("ix_todos_task_id"), "todos", ["task_id"])


def downgrade() -> None:
    op.drop_table("todos")
    op.drop_table("tasks")
