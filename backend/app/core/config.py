"""Application configuration via pydantic-settings.

All settings come from environment variables (or a local .env file).
No secrets are ever hardcoded here.
"""
from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    # JWT signing key (HS256). The dev default is rejected in production by
    # the validator below — set a real one (e.g. `secrets.token_hex(32)`).
    SECRET_KEY: str = "dev-secret-change-me"
    # Optional admin bootstrap: when BOTH are set, startup creates this
    # user (if missing) and assigns all ownerless monitors/settings rows
    # to them. Never set in tests (bootstrap is skipped when TESTING).
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    # Telegram notifications: env fallback for the credentials. A value
    # persisted in AppSettings (via the settings API) wins over env.
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None
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

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        """Accept a plain ``mysql://`` URL by rewriting it to
        ``mysql+pymysql://``. TiDB Cloud's connection dialog shows a
        plain ``mysql://`` URL; without the ``+pymysql`` driver
        qualifier SQLAlchemy defaults to ``mysql+mysqldb`` and crashes
        at import time with ``No module named 'MySQLdb'`` (pymysql is
        the only MySQL driver this project ships). Also strips
        copy-paste whitespace."""
        if not isinstance(value, str):
            return value
        value = value.strip()
        if value.startswith("mysql://"):
            value = "mysql+pymysql://" + value[len("mysql://"):]
        return value

    @model_validator(mode="after")
    def _require_secret_key_in_production(self) -> "Settings":
        """Fail fast in production without a real JWT signing key.

        Tests and local dev run with APP_ENV=development, so the dev
        default is fine there; production must set SECRET_KEY explicitly
        (Render prompts for it — see render.yaml).
        """
        if self.APP_ENV == "production" and (
            not self.SECRET_KEY or self.SECRET_KEY == "dev-secret-change-me"
        ):
            raise ValueError(
                "SECRET_KEY must be set to a strong random value when "
                "APP_ENV=production. Generate one with: python -c "
                "\"import secrets; print(secrets.token_hex(32))\""
            )
        return self

    @property
    def cors_origins(self) -> list[str]:
        # Strip a trailing slash too: browsers send the origin without
        # one, so "https://example.com/" pasted into FRONTEND_URL
        # would otherwise never match and CORS would fail.
        return [
            o.strip().rstrip("/") for o in self.FRONTEND_URL.split(",") if o.strip()
        ]


settings = Settings()
