"""Database schema (SQLAlchemy Core). The rules the API also checks are enforced
here as well, so no code path or race can break them:
- plants point to existing species, Sorte and Standort (FKs, ON DELETE RESTRICT:
  a Standort with plants, also archived ones, cannot be deleted);
- a plant's Sorte belongs to the plant's species (composite FK);
- Standort names are unique ignoring case/umlaut spelling (unique folded key);
- enum-like columns only take the allowed values (CHECKs).
Changes to this file need an Alembic migration in migrations/versions."""

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

GROWTH = ("baum", "strauch", "hecke", "kletterpflanze", "kuebel", "staude", "gras", "knolle", "gemuese", "kraut",
          "einjaehrig")  # fmt: skip
LIGHT = ("sonnig", "halbschattig", "schattig")
STANDORT_TYPE = ("beet", "gemuesebeet", "rasen", "hecke", "kuebelplatz", "gewaechshaus", "sonstiges")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


metadata = MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    }
)

settings = Table(
    "settings",
    metadata,
    Column("id", SmallInteger, primary_key=True),
    Column("data", JSONB, nullable=False),
    Column("schema_version", Integer, nullable=False),
    CheckConstraint("id = 1", name="single_row"),
)

species = Table(
    "species",
    metadata,
    Column("id", Text, primary_key=True),
    Column("latin", Text, nullable=False, unique=True),
    Column("family", Text),
    Column("german", ARRAY(Text), nullable=False),
    Column("synonyms", ARRAY(Text), nullable=False),
    Column("growth", Text, nullable=False),
    Column("woody", Boolean, nullable=False),
    Column("feeder", Text),
    Column("source", Text, nullable=False),
    CheckConstraint(_in("growth", GROWTH), name="growth"),
    CheckConstraint("feeder IS NULL OR " + _in("feeder", ("stark", "mittel", "schwach")), name="feeder"),
    CheckConstraint(_in("source", ("seed", "user")), name="source"),
)

cultivars = Table(
    "cultivars",
    metadata,
    Column("id", Text, primary_key=True),
    Column("species_id", Text, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False, index=True),
    Column("name", Text, nullable=False),
    Column("synonyms", ARRAY(Text), nullable=False),
    Column("source", Text, nullable=False),
    UniqueConstraint("id", "species_id", name="uq_cultivars_id_species"),  # target of the plants composite FK
    CheckConstraint(_in("source", ("seed", "user")), name="source"),
)

standorte = Table(
    "standorte",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_key", Text, nullable=False, unique=True),
    Column("light", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("notes", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("light", LIGHT), name="light"),
    CheckConstraint(_in("type", STANDORT_TYPE), name="type"),
)

plants = Table(
    "plants",
    metadata,
    Column("id", Text, primary_key=True),
    Column("species_id", Text, ForeignKey("species.id", ondelete="RESTRICT"), nullable=False),
    Column("cultivar_id", Text),
    Column("standort_id", Text, ForeignKey("standorte.id", ondelete="RESTRICT"), nullable=False),
    Column("nickname", Text),
    Column("form", Text),
    Column("rootstock", Text),
    Column("planted_year", Integer),
    Column("girth_cm", Integer),
    Column("in_container", Boolean, nullable=False),
    Column("notes", Text, nullable=False),
    Column("archived_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["cultivar_id", "species_id"],
        ["cultivars.id", "cultivars.species_id"],
        name="fk_plants_cultivar_of_species",
        ondelete="RESTRICT",
    ),
    Index("ix_plants_standort_id", "standort_id"),
    Index("ix_plants_archived_at", "archived_at"),
)

# No watering category: garden plants never get watering tasks (F-CP-6); indoor plants (M11) will add it.
TASK_CATEGORY = ("schnitt", "duengen", "ernte", "pflanzenschutz", "winterschutz", "aussaat", "sonstiges")
TASK_SOURCE = ("manual", "plan", "chat", "alert", "diagnosis")

tasks = Table(
    "tasks",
    metadata,
    Column("id", Text, primary_key=True),
    Column("plant_id", Text, ForeignKey("plants.id", ondelete="RESTRICT"), index=True),
    Column("title", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("instructions", Text, nullable=False),
    Column("recurrence", Text, nullable=False),
    Column("due_date", Date),
    Column("month_from", SmallInteger),
    Column("month_to", SmallInteger),
    Column("interval_days", Integer),
    Column("start_date", Date),
    Column("urgent", Boolean, nullable=False),
    Column("source", Text, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("generation", Integer, nullable=False),  # +1 on every timing change; occurrences keep theirs
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("category", TASK_CATEGORY), name="category"),
    CheckConstraint(_in("source", TASK_SOURCE), name="source"),
    CheckConstraint(
        "(recurrence = 'once' AND due_date IS NOT NULL)"
        " OR (recurrence = 'yearly' AND month_from BETWEEN 1 AND 12 AND month_to BETWEEN 1 AND 12)"
        " OR (recurrence = 'interval' AND interval_days > 0)",
        name="timing",
    ),
)

todos = Table(
    "todos",
    metadata,
    Column("id", Text, primary_key=True),
    Column("task_id", Text, ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False, index=True),
    Column("generation", Integer, nullable=False),
    Column("period", Text, nullable=False),
    Column("due_from", Date, nullable=False),
    Column("due_to", Date, nullable=False),
    Column("status", Text, nullable=False),
    Column("done_at", DateTime(timezone=True)),
    Column("note", Text, nullable=False),
    Column("postponed", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # makes creating occurrences idempotent; a timing change starts a new generation, so old
    # occurrences (history) never block new ones and are never renamed or deleted
    UniqueConstraint("task_id", "generation", "period", name="uq_todos_task_period"),
    CheckConstraint(_in("status", ("open", "done", "skipped")), name="status"),
    CheckConstraint("due_to >= due_from", name="window"),
    CheckConstraint("(status = 'open') = (done_at IS NULL)", name="done_at"),
    Index("ix_todos_status_due_from", "status", "due_from"),
)
