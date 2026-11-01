"""The chat tools' own role (ticket 034): read the garden, add proposals, nothing else.
The password is set by `migrate` on every deploy (BW_MCP_DB_PASSWORD, host .env);
without it the role cannot log in.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

READ = (
    "settings",
    "standorte",
    "plants",
    "species",
    "cultivars",
    "care_plans",
    "tasks",
    "todos",
    "pheno_events",
    "pheno_normals",
    "weather_alerts",
    "chat_actions",
)  # fmt: skip (no kv: no tool reads it)


def upgrade() -> None:
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'blattwerk_mcp') THEN "
               "CREATE ROLE blattwerk_mcp NOLOGIN; END IF; END $$")  # fmt: skip
    bind = op.get_bind()
    db = bind.dialect.identifier_preparer.quote(bind.engine.url.database or "")
    op.execute(f"GRANT CONNECT ON DATABASE {db} TO blattwerk_mcp")
    op.execute("GRANT USAGE ON SCHEMA public TO blattwerk_mcp")
    op.execute(f"GRANT SELECT ON {', '.join(READ)} TO blattwerk_mcp")
    op.execute("GRANT INSERT ON chat_actions TO blattwerk_mcp")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON {', '.join(READ)} FROM blattwerk_mcp")
    op.execute("REVOKE USAGE ON SCHEMA public FROM blattwerk_mcp")
