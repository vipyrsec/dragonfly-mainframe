from pydantic import BaseSettings


class Settings(BaseSettings):
    email_recipient: str
    bcc_recipients: set[str] = set()

    class Config(BaseSettings.Config):
        env_file = ".env"


settings = Settings()  # pyright: ignore
