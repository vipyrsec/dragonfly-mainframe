from os import getenv

from pydantic_settings import BaseSettings, SettingsConfigDict

# Git SHA for Sentry
GIT_SHA = getenv("GIT_SHA", "development")


class EnvConfig(BaseSettings):
    """Our default configuration for models that should load from .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


class Mainframe(EnvConfig):
    client_origin_url: str = ""
    auth0_domain: str = ""
    auth0_audience: str = ""

    email_recipient: str
    bcc_recipients: set[str] = set()

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432"

    dragonfly_github_token: str

    job_timeout: int = 60 * 2


mainframe_settings = Mainframe()  # pyright: ignore


class _Sentry(EnvConfig):
    EnvConfig.model_config["env_prefix"] = "sentry_"

    dsn: str = ""
    environment: str = ""
    release_prefix: str = ""


Sentry = _Sentry()  # pyright: ignore


class Microsoft(EnvConfig):
    EnvConfig.model_config["env_prefix"] = "microsoft_"

    tenant_id: str
    client_id: str
    client_secret: str


microsoft_settings = Microsoft()  # pyright: ignore
