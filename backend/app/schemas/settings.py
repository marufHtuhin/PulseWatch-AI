"""Settings request/response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    default_interval_seconds: int
    default_timeout_seconds: int
    default_latency_threshold_ms: int
    max_concurrency: int
    # True when the SELECTED AI provider (see ai_provider) has a key
    # configured. The key itself is never returned in any response.
    ai_configured: bool
    # "openrouter" (default) or "gemini" — from the AI_PROVIDER env var.
    ai_provider: str
    allow_local_urls: bool
    app_env: str
    telegram_enabled: bool
    telegram_min_severity: str
    # True when a bot token AND a chat id are available (DB or env).
    # The token itself is never returned in any response.
    telegram_configured: bool
    # The effective chat id (DB value, env fallback). A chat id is a plain
    # numeric identifier, not a secret, so returning it is safe — and the
    # Settings UI needs it to keep the field filled after a save.
    telegram_chat_id: str = ""
    retention_days: int
    alert_retention_days: int


class SettingsUpdate(BaseModel):
    """Any subset of the mutable defaults. ai_configured / ai_provider /
    app_env are read-only (they come from env config).

    telegram_bot_token: send "********" to keep the stored value (same
    pattern as monitor secret headers), null to clear it (env fallback
    then applies), or a new token to replace it.
    """

    default_interval_seconds: int | None = Field(default=None, ge=30)
    default_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    default_latency_threshold_ms: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=50)
    telegram_enabled: bool | None = None
    telegram_min_severity: Literal["warning", "high", "critical"] | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    retention_days: int | None = Field(default=None, ge=7, le=365)
    alert_retention_days: int | None = Field(default=None, ge=30, le=1095)


class CleanupResult(BaseModel):
    """Counts from a retention cleanup (or a preview of one)."""

    records_deleted: int
    alerts_deleted: int
    anomalies_deleted: int


class TestNotificationResult(BaseModel):
    """Result of POST /api/settings/test-notification."""

    success: bool
    detail: str
