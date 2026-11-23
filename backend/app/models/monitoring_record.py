"""MonitoringRecord model: metadata of one check.

Response bodies are NEVER stored — only metrics, status, and a short
error message.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.anomaly import Anomaly
    from app.models.monitor import Monitor


class MonitoringRecord(Base):
    __tablename__ = "monitoring_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_returned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_valid_json: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="records")
    anomalies: Mapped[list["Anomaly"]] = relationship(
        "Anomaly", back_populates="record", cascade="all, delete-orphan", passive_deletes=True
    )
