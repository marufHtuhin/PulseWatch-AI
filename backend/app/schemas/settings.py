"""Settings request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    default_interval_seconds: int
    default_timeout_seconds: int
    default_latency_threshold_ms: int
    max_concurrency: int
    gemini_configured: bool
    allow_local_urls: bool
    app_env: str


class SettingsUpdate(BaseModel):
    """Any subset of the mutable defaults. gemini_configured / app_env are
    read-only (they come from env config)."""

    default_interval_seconds: int | None = Field(default=None, ge=30)
    default_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    default_latency_threshold_ms: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1, le=50)
