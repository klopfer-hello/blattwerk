"""Indoor Standorte have no light (sonnig/halbschattig/schattig): in a room the window and
the distance to it, stored on the plant, decide (M11, user feedback).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-01
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("standorte", "light", nullable=True)
    op.execute("UPDATE standorte SET light = NULL WHERE type = 'zimmer'")
    op.create_check_constraint(op.f("ck_standorte_light_outdoors"), "standorte", "(type = 'zimmer') = (light IS NULL)")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_standorte_light_outdoors"), "standorte", type_="check")
    op.execute("UPDATE standorte SET light = 'halbschattig' WHERE light IS NULL")
    op.alter_column("standorte", "light", nullable=False)
