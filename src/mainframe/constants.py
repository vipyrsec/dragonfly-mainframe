from os import getenv

from pydantic import BaseSettings

# Git SHA for Sentry
GIT_SHA = getenv("GIT_SHA", "development")


class Mainframe(BaseSettings):
    class Config(BaseSettings.Config):
        env_file = ".env"

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
    class Config(BaseSettings.Config):
        env_prefix = "sentry_"
        env_file = ".env"

    dsn: str = ""
    environment: str = ""
    release_prefix: str = ""


Sentry = _Sentry()  # pyright: ignore


class Microsoft(BaseSettings):
    class Config(BaseSettings.Config):
        env_prefix = "microsoft_"
        env_file = ".env"

    tenant_id: str
    client_id: str
    client_secret: str


microsoft_settings = Microsoft()  # pyright: ignore
