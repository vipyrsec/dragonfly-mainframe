from pydantic import BaseSettings


class Mainframe(BaseSettings):
    class Config(BaseSettings.Config):
        env_file = ".env"

    production: bool = True

    client_origin_url: str = ""
    auth0_domain: str = ""
    auth0_audience: str = ""

    email_recipient: str
    bcc_recipients: set[str] = set()

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432"

    dragonfly_github_token: str

    job_timeout: int = 60 * 2


mainframe_settings = Mainframe()  # pyright: ignore


class Microsoft(BaseSettings):
    class Config(BaseSettings.Config):
        env_prefix = "microsoft_"
        env_file = ".env"

    tenant_id: str
    client_id: str
    client_secret: str


microsoft_settings = Microsoft()  # pyright: ignore
