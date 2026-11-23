"""Application configuration via pydantic-settings.

All settings come from environment variables (or a local .env file).
No secrets are ever hardcoded here.
"""
from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "sqlite:///./pulsewatch.db"
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    FRONTEND_URL: str = "http://localhost:5173"
    ALLOW_LOCAL_URLS: bool = False
    MAX_CONCURRENCY: int = 10
    MAX_BATCH_SIZE: int = 50
    # Hard cap on how many response bytes are ever read from a monitored API.
    # Bodies are never stored; this only bounds memory while parsing metadata.
    MAX_RESPONSE_READ_BYTES: int = 10 * 1024 * 1024
    # When true (env PULSEWATCH_TESTING=1 or TESTING=1) the scheduler does not
    # start in the lifespan hook, so importing the app under pytest is safe.
    TESTING: bool = Field(
        default=False,
        validation_alias=AliasChoices("PULSEWATCH_TESTING", "TESTING"),
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.FRONTEND_URL.split(",") if o.strip()]


settings = Settings()
