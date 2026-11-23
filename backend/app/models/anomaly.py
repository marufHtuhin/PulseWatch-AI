"""Anomaly model: one deterministic rule hit on one check."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.monitor import Monitor
    from app.models.monitoring_record import MonitoringRecord


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # HIGH_RESPONSE_TIME | HTTP_ERROR | TIMEOUT | NETWORK_ERROR |
    # ZERO_RECORDS | INVALID_RESPONSE | MISSING_FIELDS | LARGE_RESPONSE |
    # UNEXPECTED_STATUS | HISTORICAL_ANOMALY | SSL_EXPIRING
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # info | warning | high | critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="anomalies")
    record: Mapped["MonitoringRecord"] = relationship("MonitoringRecord", back_populates="anomalies")
