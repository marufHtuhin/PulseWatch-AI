"""Alert model: a user-facing incident, deduplicated per (monitor, type)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.monitor import Monitor


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Points at the most recent anomaly of this type (updated on dedup bumps).
    # SET NULL if that anomaly row is deleted; the alert itself survives.
    anomaly_id: Mapped[int | None] = mapped_column(
        ForeignKey("anomalies.id", ondelete="SET NULL"), nullable=True
    )
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    possible_cause: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    # active | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="alerts")
