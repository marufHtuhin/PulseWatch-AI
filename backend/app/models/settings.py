"""AppSettings model: a single-row table (id always 1) of user defaults."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow


class AppSettings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    default_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    default_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    default_latency_threshold_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # Telegram notifications. Credentials here win over the env vars
    # (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). The token is never returned
    # by any API response — see the settings routes.
    telegram_bot_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_min_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    # Data retention (days). Records older than retention_days are deleted;
    # resolved alerts older than alert_retention_days are deleted.
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    alert_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
