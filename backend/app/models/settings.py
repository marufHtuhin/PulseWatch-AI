"""AppSettings model: a single-row table (id always 1) of user defaults."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
