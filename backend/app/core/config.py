import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]


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
    db_password: SecretStr = Field(default=SecretStr(""))
    database_url_value: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    secret_key: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=60, gt=0)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )
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
        validation_alias=AliasChoices(
            "GEMINI_SECOND_FALLBACK_MODEL", "gemini_second_fallback_model"
        ),
    )

    @field_validator("database_url_value", mode="before")
    @classmethod
    def blank_database_url_is_unset(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                value = json.loads(text)
            else:
                value = [item.strip() for item in text.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip().rstrip("/") for item in value if str(item).strip()]
        return value

    @model_validator(mode="after")
    def require_database_credentials(self) -> "Settings":
        if self.database_url_value is None and not self.db_password.get_secret_value():
            raise ValueError("Set DATABASE_URL or DB_PASSWORD")
        return self

    @property
    def database_url(self) -> URL:
        if self.database_url_value is not None:
            url = make_url(self.database_url_value.get_secret_value())
            if url.drivername in {"postgres", "postgresql"}:
                return url.set(drivername="postgresql+psycopg")
            if url.get_backend_name() == "postgresql":
                return url
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
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
