"""Runtime configuration from the environment (prefix GP_). The database URL
holds the password: SecretStr keeps it out of repr, logs and errors."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GP_", frozen=True)

    database_url: SecretStr = SecretStr("postgresql+psycopg://localhost/garten_planer")
    version: str = "dev"
    db_timeout_s: int = 3
    # Web push (M3b). The api only needs the public key; the private key is given
    # to the worker container only. The subject is a contact the push services may
    # use; it must not be a personal address (repo rule), example.com is reserved.
    vapid_public: str = ""
    vapid_private: SecretStr = SecretStr("")
    vapid_subject: str = "mailto:garten-planer@example.com"
