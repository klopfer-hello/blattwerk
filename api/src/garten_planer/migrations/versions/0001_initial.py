"""Initial schema: settings, species, cultivars, standorte, plants (M2b).

Revision ID: 0001
Revises:
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from garten_planer.schema import GROWTH, LIGHT, STANDORT_TYPE

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


TS = sa.DateTime(timezone=True)
TEXTS = sa.ARRAY(sa.Text)


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.SmallInteger, primary_key=True),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_settings_single_row")),
    )
    op.create_table(
        "species",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("latin", sa.Text, nullable=False),
        sa.Column("family", sa.Text),
        sa.Column("german", TEXTS, nullable=False),
        sa.Column("synonyms", TEXTS, nullable=False),
        sa.Column("growth", sa.Text, nullable=False),
        sa.Column("woody", sa.Boolean, nullable=False),
        sa.Column("feeder", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        sa.UniqueConstraint("latin", name="uq_species_latin"),
        sa.CheckConstraint(_in("growth", GROWTH), name=op.f("ck_species_growth")),
        sa.CheckConstraint(
            "feeder IS NULL OR " + _in("feeder", ("stark", "mittel", "schwach")), name=op.f("ck_species_feeder")
        ),
        sa.CheckConstraint(_in("source", ("seed", "user")), name=op.f("ck_species_source")),
    )
    op.create_table(
        "cultivars",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "species_id",
            sa.Text,
            sa.ForeignKey("species.id", ondelete="RESTRICT", name="fk_cultivars_species_id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("synonyms", TEXTS, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.UniqueConstraint("id", "species_id", name="uq_cultivars_id_species"),
        sa.CheckConstraint(_in("source", ("seed", "user")), name=op.f("ck_cultivars_source")),
    )
    op.create_index("ix_cultivars_species_id", "cultivars", ["species_id"])
    op.create_table(
        "standorte",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_key", sa.Text, nullable=False),
        sa.Column("light", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("name_key", name="uq_standorte_name_key"),
        sa.CheckConstraint(_in("light", LIGHT), name=op.f("ck_standorte_light")),
        sa.CheckConstraint(_in("type", STANDORT_TYPE), name=op.f("ck_standorte_type")),
    )
    op.create_table(
        "plants",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "species_id",
            sa.Text,
            sa.ForeignKey("species.id", ondelete="RESTRICT", name="fk_plants_species_id"),
            nullable=False,
        ),
        sa.Column("cultivar_id", sa.Text),
        sa.Column(
            "standort_id",
            sa.Text,
            sa.ForeignKey("standorte.id", ondelete="RESTRICT", name="fk_plants_standort_id"),
            nullable=False,
        ),
        sa.Column("nickname", sa.Text),
        sa.Column("form", sa.Text),
        sa.Column("rootstock", sa.Text),
        sa.Column("planted_year", sa.Integer),
        sa.Column("girth_cm", sa.Integer),
        sa.Column("in_container", sa.Boolean, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("archived_at", TS),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["cultivar_id", "species_id"],
            ["cultivars.id", "cultivars.species_id"],
            name="fk_plants_cultivar_of_species",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_plants_standort_id", "plants", ["standort_id"])
    op.create_index("ix_plants_archived_at", "plants", ["archived_at"])


def downgrade() -> None:
    for table in ("plants", "standorte", "cultivars", "species", "settings"):
        op.drop_table(table)
