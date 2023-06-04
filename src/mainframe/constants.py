from pydantic import BaseSettings


class Microsoft(BaseSettings):
    tenant_id: str
    client_id: str
    client_secret: str

    class Config(BaseSettings.Config):
        env_prefix = "microsoft_"
        env_file = ".env"


microsoft_settings = Microsoft()  # pyright: ignore


class Mainframe(BaseSettings):
    client_origin_url: str
    auth0_domain: str
    auth0_audience: str

    email_recipient: str
    bcc_recipients: set[str] = set()

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432"

    dragonfly_github_token: str

    class Config(BaseSettings.Config):
        env_file = ".env"


mainframe_settings = Mainframe()  # pyright: ignore
