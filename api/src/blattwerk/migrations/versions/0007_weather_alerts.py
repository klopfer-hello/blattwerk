"""Weather alerts (M6b): alerts per event, alert tasks.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "weather_alerts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("family", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("pushed_value", sa.Float),
        sa.Column("first_at", TS, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(
            "kind IN ('frost', 'strong_frost', 'late_frost', 'heat', 'storm')", name=op.f("ck_weather_alerts_kind")
        ),
        sa.CheckConstraint("status IN ('active', 'cancelled', 'past')", name=op.f("ck_weather_alerts_status")),
        sa.CheckConstraint("family IN ('frost', 'heat', 'storm')", name=op.f("ck_weather_alerts_family")),
        sa.UniqueConstraint("family", "day", name=op.f("uq_weather_alerts_family_day")),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "alert_id", sa.Text, sa.ForeignKey("weather_alerts.id", ondelete="RESTRICT", name=op.f("fk_tasks_alert_id"))
        ),
    )
    op.add_column("tasks", sa.Column("alert_action", sa.Text))
    op.create_index(
        op.f("uq_tasks_alert_action"),
        "tasks",
        ["alert_id", "alert_action"],
        unique=True,
        postgresql_where=sa.text("alert_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f("uq_tasks_alert_action"), table_name="tasks")
    op.drop_column("tasks", "alert_action")
    op.drop_column("tasks", "alert_id")
    op.drop_table("weather_alerts")
