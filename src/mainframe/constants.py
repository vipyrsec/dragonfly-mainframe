from pydantic import BaseSettings


class MicrosoftSettings(BaseSettings):
    tenant_id: str
    client_id: str
    client_secret: str

    class Config(BaseSettings.Config):
        env_prefix = "MICROSOFT_"
        env_file = ".env"


microsoft_settings = MicrosoftSettings()  # pyright: ignore


class Settings(BaseSettings):
    email_recipient: str
    bcc_recipients: set[str] = set()

    db_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432"

    class Config(BaseSettings.Config):
        env_file = ".env"


settings = Settings()  # pyright: ignore
