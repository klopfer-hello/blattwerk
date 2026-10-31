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
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

GROWTH = ("baum", "strauch", "hecke", "kletterpflanze", "kuebel", "staude", "gras", "knolle", "gemuese", "kraut",
          "einjaehrig")  # fmt: skip
LIGHT = ("sonnig", "halbschattig", "schattig")
STANDORT_TYPE = ("beet", "gemuesebeet", "rasen", "hecke", "kuebelplatz", "gewaechshaus", "sonstiges", "zimmer")
INDOOR = "zimmer"  # the one indoor type (M11): watering yes; weather, frost, phenology and § 39 no
WINDOW = ("N", "O", "S", "W", "keins")
WINDOW_DISTANCE = ("fensterbank", "bis_1m", "1_2m", "raum")
POT_MATERIAL = ("kunststoff", "ton", "keramik", "glas")


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
    Column("hardiness_c", SmallInteger),  # lowest °C an established plant survives in the ground (F-WX-5)
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
    Column("light", Text),  # outdoors only; indoors the window on the plant counts (M11)
    Column("type", Text, nullable=False),
    Column("notes", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("light", LIGHT), name="light"),
    CheckConstraint(_in("type", STANDORT_TYPE), name="type"),
    CheckConstraint("(type = 'zimmer') = (light IS NULL)", name="light_outdoors"),
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
    Column("window_dir", Text),  # indoor only (M11): direction of the nearest window
    Column("window_distance", Text),
    Column("pot_cm", SmallInteger),
    Column("pot_material", Text),
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
    CheckConstraint(_in("window_dir", WINDOW), name="window_dir"),
    CheckConstraint(_in("window_distance", WINDOW_DISTANCE), name="window_distance"),
    CheckConstraint("pot_cm BETWEEN 3 AND 200", name="pot_cm"),
    CheckConstraint(_in("pot_material", POT_MATERIAL), name="pot_material"),
)

# Watering, misting and dusting only for indoor plants (M11); garden plants never get watering (F-CP-6).
INDOOR_CATEGORIES = ("giessen", "bespruehen", "entstauben")  # checked in the routes
TASK_CATEGORY = ("schnitt", "duengen", "ernte", "pflanzenschutz", "winterschutz", "aussaat", "sonstiges",
                 *INDOOR_CATEGORIES)  # fmt: skip
TASK_SOURCE = ("manual", "plan", "chat", "alert", "diagnosis")

tasks = Table(
    "tasks",
    metadata,
    Column("id", Text, primary_key=True),
    Column("plant_id", Text, ForeignKey("plants.id", ondelete="RESTRICT"), index=True),
    Column("title", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("cut_type", Text),  # Schnitt only: pflege (gentle) | stark (strong): decides §39 (legal.py)
    Column("instructions", Text, nullable=False),
    Column("recurrence", Text, nullable=False),
    Column("due_date", Date),
    Column("month_from", SmallInteger),
    Column("month_to", SmallInteger),
    Column("interval_days", Integer),
    Column("winter_interval_days", Integer),  # interval in Nov-Feb (indoor watering, M11)
    Column("start_date", Date),
    Column("pheno_phase", Text),  # F-WX-3: window from this phase start (M7); month window = fallback
    Column("pheno_offset", SmallInteger, nullable=False, server_default="0"),
    Column("pheno_window", SmallInteger, nullable=False, server_default="14"),
    Column("urgent", Boolean, nullable=False),
    Column("source", Text, nullable=False),
    Column("plan_id", Text, ForeignKey("care_plans.id", ondelete="RESTRICT")),  # source "plan": which plan
    Column("products", JSONB, nullable=False, server_default=text("'[]'::jsonb")),  # plan tasks: products/brands
    Column("why", Text, nullable=False, server_default=""),  # plan tasks: one sentence why
    Column("retired", Boolean, nullable=False, server_default=false()),  # replaced by a newer plan: history only
    Column("alert_id", Text, ForeignKey("weather_alerts.id", ondelete="RESTRICT")),  # source "alert"
    Column("alert_action", Text),  # which action of the alert (kuebel, gewaechshaus, ...)
    Column("enabled", Boolean, nullable=False),
    Column("generation", Integer, nullable=False),  # +1 on every timing change; occurrences keep theirs
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("category", TASK_CATEGORY), name="category"),
    CheckConstraint(_in("source", TASK_SOURCE), name="source"),
    Index(  # one task per action and alert
        "uq_tasks_alert_action",
        "alert_id",
        "alert_action",
        unique=True,
        postgresql_where=text("alert_id IS NOT NULL"),
    ),
    CheckConstraint(
        "(category = 'schnitt' AND cut_type IN ('pflege', 'stark')) OR (category <> 'schnitt' AND cut_type IS NULL)",
        name="cut_type",
    ),
    CheckConstraint(
        "(recurrence = 'once' AND due_date IS NOT NULL)"
        " OR (recurrence = 'yearly' AND month_from BETWEEN 1 AND 12 AND month_to BETWEEN 1 AND 12)"
        " OR (recurrence = 'interval' AND interval_days > 0)",
        name="timing",
    ),
    CheckConstraint(
        "winter_interval_days IS NULL OR (recurrence = 'interval' AND winter_interval_days > 0)",
        name="winter_interval",
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
    Column("soil", Text),  # watering (M11): how the soil was before; adjusted the interval once
    Column("postponed", Boolean, nullable=False),
    Column("notified_at", DateTime(timezone=True)),  # included in a push digest (sent once)
    Column("legal_adjustment", Text),  # why the window was moved or shortened (legal.py), shown to the user
    Column("created_at", DateTime(timezone=True), nullable=False),
    # makes creating occurrences idempotent; a timing change starts a new generation, so old
    # occurrences (history) never block new ones and are never renamed or deleted
    UniqueConstraint("task_id", "generation", "period", name="uq_todos_task_period"),
    CheckConstraint(_in("status", ("open", "done", "skipped")), name="status"),
    CheckConstraint(_in("soil", ("feucht", "passt", "trocken")), name="soil"),
    CheckConstraint("due_to >= due_from", name="window"),
    CheckConstraint("(status = 'open') = (done_at IS NULL)", name="done_at"),
    Index("ix_todos_status_due_from", "status", "due_from"),
)

push_subs = Table(  # one row per device that allowed push (personal data: volume only)
    "push_subs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("endpoint", Text, nullable=False, unique=True),
    Column("p256dh", Text, nullable=False),
    Column("auth", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_ok_at", DateTime(timezone=True)),
    Column("auth_failures", Integer, nullable=False, server_default="0"),  # 401/403 periods in a row (old keys)
    Column("auth_failed_at", DateTime(timezone=True)),  # when the last counted 401/403 came
)

push_messages = Table(  # outbox: the api writes, the worker (only one with internet) sends
    "push_messages",
    metadata,
    Column("id", Text, primary_key=True),
    Column("sub_id", Text, ForeignKey("push_subs.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True)),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text),
)

kv = Table(  # small job state (e.g. date of the last digest)
    "kv",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSONB, nullable=False),
)

care_plans = Table(  # one per Claude run that succeeded (F-AI-5: model, prompt version, cost kept)
    "care_plans",
    metadata,
    Column("id", Text, primary_key=True),
    Column("plant_id", Text, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("cost_usd", Float),
    Column("summary", Text, nullable=False),
    Column("confidence", Text, nullable=False),
    Column("caveats", Text, nullable=False),
    Column("pests", JSONB, nullable=False),
    Column("dropped", Integer, nullable=False),  # tasks the code-side checks threw away
    CheckConstraint(_in("confidence", ("low", "medium", "high")), name="confidence"),
)

plan_jobs = Table(  # queue: the api adds, the worker (internet) runs Claude
    "plan_jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("plant_id", Text, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False, index=True),
    Column("status", Text, nullable=False),
    Column("error", Text),
    Column("plan_id", Text, ForeignKey("care_plans.id", ondelete="RESTRICT")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(_in("status", ("queued", "running", "done", "failed")), name="status"),
    Index("ix_plan_jobs_status_created_at", "status", "created_at"),
    Index(  # at most one active job per plant, whoever writes
        "uq_plan_jobs_active_plant",
        "plant_id",
        unique=True,
        postgresql_where=text("status IN ('queued', 'running')"),
    ),
)

name_jobs = Table(  # AI name suggestions (F-AI-3): the typed name in, candidates out
    "name_jobs",
    metadata,
    Column("id", Text, primary_key=True),
    Column("query", Text, nullable=False),
    Column("photo_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),  # plant ID by photo (M11)
    Column("status", Text, nullable=False),
    Column("error", Text),
    Column("candidates", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("model", Text),
    Column("cost_usd", Float),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(_in("status", ("queued", "running", "done", "failed")), name="status"),
    Index("ix_name_jobs_status_created_at", "status", "created_at"),
)

weather_alerts = Table(  # one per weather event (kind + local day), F-WX-4; written by wetterwacht
    "weather_alerts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("family", Text, nullable=False),  # frost | heat | storm: one alert per family and day
    Column("kind", Text, nullable=False),  # within frost: frost, strong_frost or late_frost (can change)
    Column("day", Date, nullable=False),
    Column("value", Float, nullable=False),  # current forecast extreme (°C or km/h)
    Column("pushed_value", Float),  # what the last push said; a new push only when clearly worse
    Column("first_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("kind", ("frost", "strong_frost", "late_frost", "heat", "storm")), name="kind"),
    CheckConstraint(_in("status", ("active", "cancelled", "past")), name="status"),
    CheckConstraint(_in("family", ("frost", "heat", "storm")), name="family"),
    UniqueConstraint("family", "day", name="uq_weather_alerts_family_day"),
)

pheno_events = Table(  # entry date of an indicator phase per year and source (M7, F-WX-2)
    "pheno_events",
    metadata,
    Column("year", Integer, primary_key=True),
    Column("phase", Text, primary_key=True),
    Column("source", Text, primary_key=True),  # dwd (region median) | garten (own observation)
    Column("day", Date, nullable=False),
    Column("reports", Integer, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("source", ("dwd", "garten")), name="source"),
)

pheno_normals = Table(  # long-term median day of year 1991-2020 per phase in the region
    "pheno_normals",
    metadata,
    Column("phase", Text, primary_key=True),
    Column("doy", Integer, nullable=False),
    Column("stations", Integer, nullable=False),  # number of (station, year) values behind it
    Column("computed_at", DateTime(timezone=True), nullable=False),
)

chats = Table(  # garden chat (M8, F-AI-4): one conversation
    "chats",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("plant_id", Text, ForeignKey("plants.id", ondelete="SET NULL")),  # "Pflanze krank?": the plant asked about
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

chat_messages = Table(  # user question or assistant answer; the worker fills the answer while it streams
    "chat_messages",
    metadata,
    Column("id", Text, primary_key=True),
    Column("chat_id", Text, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("role", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("photos", JSONB, nullable=False, server_default=text("'[]'::jsonb")),  # photo ids of a question (M9)
    Column("status", Text, nullable=False),
    Column("error", Text),
    Column("model", Text),
    Column("cost_usd", Float),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(_in("role", ("user", "assistant")), name="role"),
    CheckConstraint(_in("status", ("queued", "running", "done", "failed")), name="status"),
    Index("ix_chat_messages_status_created_at", "status", "created_at"),
)

chat_actions = Table(  # what the chat proposes; only the user's "Ja" carries it out (no writes by the AI)
    "chat_actions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("message_id", Text, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("result_id", Text),  # the task created, or the plant noted
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True)),
    CheckConstraint(_in("kind", ("aufgabe", "notiz", "diagnose")), name="kind"),
    CheckConstraint(_in("status", ("proposed", "done", "rejected")), name="status"),
)

photos = Table(  # plant doctor (M9): re-encoded JPEG without metadata
    "photos",
    metadata,
    Column("id", Text, primary_key=True),
    Column("data", LargeBinary, nullable=False),
    Column("width", Integer, nullable=False),
    Column("height", Integer, nullable=False),
    Column("message_id", Text, ForeignKey("chat_messages.id", ondelete="SET NULL"), index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

diagnoses = Table(  # a diagnosis the user saved from the chat; part of the plant's history
    "diagnoses",
    metadata,
    Column("id", Text, primary_key=True),
    Column("plant_id", Text, ForeignKey("plants.id", ondelete="RESTRICT"), nullable=False, index=True),
    Column("title", Text, nullable=False),
    Column("confidence", Text, nullable=False),
    Column("cause", Text, nullable=False),
    Column("photo_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("message_id", Text, ForeignKey("chat_messages.id", ondelete="SET NULL")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(_in("confidence", ("ziemlich sicher", "sicher")), name="confidence"),
)
