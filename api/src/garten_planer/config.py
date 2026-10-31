"""Runtime configuration from the environment (prefix GP_). The database URL
holds the password: SecretStr keeps it out of repr, logs and errors."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    # empty values count as unset: compose passes "${GP_LAT:-}" when weather is not configured
    model_config = SettingsConfigDict(env_prefix="GP_", frozen=True, env_ignore_empty=True)

    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/garten_planer")
    version: str = "dev"
    db_timeout_s: int = 3
    # Web push (M3b). The api only needs the public key; the private key is given
    # to the worker container only. The subject is a contact the push services may
    # use; it must not be a personal address (repo rule), example.com is reserved.
    vapid_public: str = ""
    vapid_private: SecretStr = SecretStr("")
    vapid_subject: str = "mailto:garten-planer@example.com"
    # Care plans (M5), worker only. The CLI itself is configured in claude_cli.
    plan_model: str = "sonnet"
    plan_budget_usd: float = 0.50  # per plan, enforced by the CLI
    plan_daily_limit: int = 60  # plan runs per day for the whole garden
    name_budget_usd: float = 0.20  # per name lookup
    name_daily_limit: int = 100
    chat_daily_limit: int = 150  # chat answers per day
    chat_budget_usd: float = 0.30  # per answer
    mcp_db_password: SecretStr = SecretStr("")  # the chat tools' own role (ticket 034), from the host .env
    # Weather (M6). Coordinates and HA entities live only in the host's .env.
    influx_url: str = "http://influxdb:8181"
    influx_token: SecretStr = SecretStr("")
    lat: float | None = None
    lon: float | None = None
