"""Runtime configuration from the environment (prefix GP_). The database URL
holds the password: SecretStr keeps it out of repr, logs and errors."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GP_", frozen=True)

    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/garten_planer")
    version: str = "dev"
    db_timeout_s: int = 3
