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

    # reporter_url: str = "" # Deprecar

    db_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/dragonfly"
    db_connection_pool_max_size: int = 15
    """The max number of concurrent connections"""
    db_connection_pool_persistent_size: int = 5
    """The number of concurrent connections to maintain in the connection pool"""

    dragonfly_github_token: str

    job_timeout: int = 60 * 2


mainframe_settings = Mainframe()  # pyright: ignore


class PyPI(EnvConfig):  # pyright: ignore
    """Environment variables for PyPI."""

    pypi_base_url: str = "https://pypi.org/danger-api"
    pypi_api_token: str = ""


pypi = PyPI()

class _Sentry(EnvConfig, env_prefix="sentry_"):  # pyright: ignore
    dsn: str = ""
    environment: str = "production"
    release_prefix: str = "dragonfly-mainframe"


Sentry = _Sentry()  # pyright: ignore
