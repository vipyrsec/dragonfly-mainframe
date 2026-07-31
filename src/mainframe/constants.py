from os import getenv

from pydantic import PositiveInt, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Git SHA for Sentry
GIT_SHA = getenv("GIT_SHA", "development")
STAGING_API_ORIGIN = "https://dragonfly-staging.vipyrsec.com"


class EnvConfig(BaseSettings):
    """Our default configuration for models that should load from .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


class Mainframe(EnvConfig):
    environment: str = "production"
    client_origin_url: str = ""

    reporter_url: str = ""

    db_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/dragonfly"
    db_connection_pool_max_size: int = 15
    """The max number of concurrent connections."""
    db_connection_pool_persistent_size: int = 5
    """The number of concurrent connections to maintain in the connection pool."""

    dragonfly_github_token: str

    job_timeout: int = 60 * 2
    max_job_attempts: PositiveInt = 3
    queue_metrics_refresh_seconds: PositiveInt = 60
    performance_metrics_refresh_seconds: PositiveInt = 15 * 60
    opengrep_shadow_enabled: bool = False

    log_config_file: str = "logging/development.toml"

    @model_validator(mode="after")
    def restrict_opengrep_shadow_to_staging(self) -> "Mainframe":
        """Reject an OpenGrep shadow stream outside staging."""
        if self.opengrep_shadow_enabled and self.environment != "staging":
            msg = "OPENGREP_SHADOW_ENABLED requires ENVIRONMENT=staging"
            raise ValueError(msg)
        return self


mainframe_settings = Mainframe()  # pyright: ignore[reportCallIssue]


class _Sentry(EnvConfig, env_prefix="sentry_"):
    dsn: str = ""
    environment: str = "production"
    release_prefix: str = "dragonfly-mainframe"


Sentry = _Sentry()


class CFAccess(EnvConfig, env_prefix="cf_access_"):
    audience: str = ""
    team_domain: str = "https://vipyrsec.cloudflareaccess.com"


cf_access_settings = CFAccess.model_validate({})


def validate_opengrep_shadow_environment() -> None:
    """Bind the shadow feature to staging's environment-specific audience."""
    if not mainframe_settings.opengrep_shadow_enabled:
        return
    if cf_access_settings.audience.rstrip("/") != STAGING_API_ORIGIN:
        msg = "OpenGrep shadow requires the staging Cloudflare Access audience"
        raise RuntimeError(msg)
