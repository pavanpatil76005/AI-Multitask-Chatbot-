from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "ai_chatbot"
    db_user: str = "postgres"
    db_password: SecretStr
    secret_key: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=60, gt=0)
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"]
    GEMINI_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "gemini_api_key"),
    )
    GEMINI_MODEL: str = Field(
        default="gemini-3.6-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "gemini_model"),
    )
    GEMINI_FALLBACK_MODEL: str | None = Field(
        default="gemini-3.5-flash",
        validation_alias=AliasChoices("GEMINI_FALLBACK_MODEL", "gemini_fallback_model"),
    )

    GEMINI_SECOND_FALLBACK_MODEL: str | None = Field(
        default="gemini-3.5-flash-lite",
        validation_alias=AliasChoices("GEMINI_SECOND_FALLBACK_MODEL", "gemini_second_fallback_model"),
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
