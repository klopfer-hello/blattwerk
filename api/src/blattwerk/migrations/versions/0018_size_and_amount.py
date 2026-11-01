"""Plant height (indoor) and the watering amount per task (user feedback on M11).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plants", sa.Column("height_cm", sa.SmallInteger))
    op.create_check_constraint(op.f("ck_plants_height_cm"), "plants", "height_cm BETWEEN 1 AND 1000")
    op.add_column("tasks", sa.Column("amount_ml", sa.Integer))
    op.create_check_constraint(
        op.f("ck_tasks_amount_ml"),
        "tasks",
        "amount_ml IS NULL OR (category = 'giessen' AND amount_ml BETWEEN 10 AND 20000)",
    )


def downgrade() -> None:
    op.drop_column("tasks", "amount_ml")
    op.drop_column("plants", "height_cm")
