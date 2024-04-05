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

    reporter_url: str = ""

    db_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432"

    dragonfly_github_token: str

    job_timeout: int = 60 * 2


mainframe_settings = Mainframe()  # pyright: ignore


class _Sentry(EnvConfig, env_prefix="sentry_"):  # pyright: ignore
    dsn: str = ""
    environment: str = "production"
    release_prefix: str = "dragonfly-mainframe"


Sentry = _Sentry()  # pyright: ignore
