"""Runtime configuration from the environment (prefix GP_). The connection
string holds the DB password: SecretStr keeps it out of repr, logs and errors."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GP_", frozen=True)

    mongo_url: SecretStr = SecretStr("mongodb://localhost:27017/")
    db_name: str = "garten_planer"
    version: str = "dev"
    db_timeout_ms: int = 3000
