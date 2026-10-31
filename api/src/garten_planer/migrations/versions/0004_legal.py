"""Legal rules (M4): cut type on tasks, legal adjustment reason on to-dos.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("cut_type", sa.Text))
    # conservative (review M4): an existing cut of unknown kind is treated as strong, i.e. moved out of
    # the bird-protection period; the user can mark it gentle in the form
    op.execute("UPDATE tasks SET cut_type = 'stark' WHERE category = 'schnitt'")
    op.create_check_constraint(
        op.f("ck_tasks_cut_type"),
        "tasks",
        "(category = 'schnitt' AND cut_type IN ('pflege', 'stark')) OR (category <> 'schnitt' AND cut_type IS NULL)",
    )
    op.add_column("todos", sa.Column("legal_adjustment", sa.Text))


def downgrade() -> None:
    op.drop_column("todos", "legal_adjustment")
    op.drop_constraint(op.f("ck_tasks_cut_type"), "tasks")
    op.drop_column("tasks", "cut_type")
