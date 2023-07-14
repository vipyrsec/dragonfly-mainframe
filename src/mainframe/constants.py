from os import getenv

from pydantic_settings import BaseSettings, SettingsConfigDict

# Git SHA for Sentry
GIT_SHA = getenv("GIT_SHA", "development")


class Mainframe(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    client_origin_url: str = ""
    auth0_domain: str = ""
    auth0_audience: str = ""

    email_recipient: str
    bcc_recipients: set[str] = set()

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432"

    dragonfly_github_token: str

    job_timeout: int = 60 * 2


mainframe_settings = Mainframe()  # pyright: ignore


class _Sentry(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="sentry_")

    dsn: str = ""
    environment: str = ""
    release_prefix: str = ""


Sentry = _Sentry()  # pyright: ignore


class Microsoft(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="microsoft_")

    tenant_id: str
    client_id: str
    client_secret: str


microsoft_settings = Microsoft()  # pyright: ignore
