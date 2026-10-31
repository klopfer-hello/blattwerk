"""Indoor plants (M11): Standort type zimmer, window and pot, watering, winter interval,
soil feedback, plant ID by photo.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

OUTDOOR = "'beet', 'gemuesebeet', 'rasen', 'hecke', 'kuebelplatz', 'gewaechshaus', 'sonstiges'"
CATEGORIES = "'schnitt', 'duengen', 'ernte', 'pflanzenschutz', 'winterschutz', 'aussaat', 'sonstiges'"


def _check(table: str, name: str, sql: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, sql)


def upgrade() -> None:
    _check("standorte", "type", f"type IN ({OUTDOOR}, 'zimmer')")
    op.add_column("plants", sa.Column("window_dir", sa.Text))
    op.add_column("plants", sa.Column("window_distance", sa.Text))
    op.add_column("plants", sa.Column("pot_cm", sa.SmallInteger))
    op.add_column("plants", sa.Column("pot_material", sa.Text))
    op.create_check_constraint(op.f("ck_plants_window_dir"), "plants", "window_dir IN ('N', 'O', 'S', 'W', 'keins')")
    op.create_check_constraint(
        op.f("ck_plants_window_distance"), "plants", "window_distance IN ('fensterbank', 'bis_1m', '1_2m', 'raum')"
    )
    op.create_check_constraint(op.f("ck_plants_pot_cm"), "plants", "pot_cm BETWEEN 3 AND 200")
    op.create_check_constraint(
        op.f("ck_plants_pot_material"), "plants", "pot_material IN ('kunststoff', 'ton', 'keramik', 'glas')"
    )
    _check("tasks", "category", f"category IN ({CATEGORIES}, 'giessen', 'bespruehen', 'entstauben')")
    # before M11 an interval ignored its months; from now on they would make it seasonal
    op.execute("UPDATE tasks SET month_from = NULL, month_to = NULL WHERE recurrence = 'interval'")
    op.add_column("tasks", sa.Column("winter_interval_days", sa.Integer))
    op.create_check_constraint(
        op.f("ck_tasks_winter_interval"),
        "tasks",
        "winter_interval_days IS NULL OR (recurrence = 'interval' AND winter_interval_days > 0)",
    )
    op.add_column("todos", sa.Column("soil", sa.Text))
    op.create_check_constraint(op.f("ck_todos_soil"), "todos", "soil IN ('feucht', 'passt', 'trocken')")
    op.add_column("name_jobs", sa.Column("photo_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("name_jobs", "photo_ids")
    op.drop_column("todos", "soil")
    op.drop_column("tasks", "winter_interval_days")
    op.execute(
        "DELETE FROM todos WHERE task_id IN"
        " (SELECT id FROM tasks WHERE category IN ('giessen', 'bespruehen', 'entstauben'))"
    )
    op.execute("DELETE FROM tasks WHERE category IN ('giessen', 'bespruehen', 'entstauben')")
    _check("tasks", "category", f"category IN ({CATEGORIES})")
    for col in ("window_dir", "window_distance", "pot_cm", "pot_material"):
        op.drop_column("plants", col)
    op.execute("UPDATE standorte SET type = 'sonstiges' WHERE type = 'zimmer'")
    _check("standorte", "type", f"type IN ({OUTDOOR})")
