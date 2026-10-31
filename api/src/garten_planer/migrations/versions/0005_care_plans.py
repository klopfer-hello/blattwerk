"""Care plans by Claude (M5): plans, plan jobs, plan columns on tasks.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "care_plans",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "plant_id",
            sa.Text,
            sa.ForeignKey("plants.id", ondelete="RESTRICT", name=op.f("fk_care_plans_plant_id")),
            nullable=False,
        ),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("cost_usd", sa.Float),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("confidence", sa.Text, nullable=False),
        sa.Column("caveats", sa.Text, nullable=False),
        sa.Column("pests", JSONB, nullable=False),
        sa.Column("dropped", sa.Integer, nullable=False),
        sa.CheckConstraint("confidence IN ('low', 'medium', 'high')", name=op.f("ck_care_plans_confidence")),
    )
    op.create_index(op.f("ix_care_plans_plant_id"), "care_plans", ["plant_id"])
    op.create_table(
        "plan_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "plant_id",
            sa.Text,
            sa.ForeignKey("plants.id", ondelete="RESTRICT", name=op.f("fk_plan_jobs_plant_id")),
            nullable=False,
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column(
            "plan_id", sa.Text, sa.ForeignKey("care_plans.id", ondelete="RESTRICT", name=op.f("fk_plan_jobs_plan_id"))
        ),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_plan_jobs_status")),
    )
    op.create_index(op.f("ix_plan_jobs_plant_id"), "plan_jobs", ["plant_id"])
    op.create_index(op.f("ix_plan_jobs_status_created_at"), "plan_jobs", ["status", "created_at"])
    op.create_index(
        op.f("uq_plan_jobs_active_plant"),
        "plan_jobs",
        ["plant_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "plan_id", sa.Text, sa.ForeignKey("care_plans.id", ondelete="RESTRICT", name=op.f("fk_tasks_plan_id"))
        ),
    )
    op.add_column("tasks", sa.Column("products", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("tasks", sa.Column("why", sa.Text, nullable=False, server_default=""))
    op.add_column("tasks", sa.Column("retired", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tasks", "retired")
    op.drop_column("tasks", "why")
    op.drop_column("tasks", "products")
    op.drop_column("tasks", "plan_id")
    op.drop_table("plan_jobs")
    op.drop_table("care_plans")
