"""Monitor model: one watched API endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.anomaly import Anomaly
    from app.models.monitoring_record import MonitoringRecord


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    # Request headers as stored (secret values kept verbatim in the DB;
    # they are masked to "********" at the API boundary, never here).
    headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    expected_status_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: [200])
    expected_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    check_zero_records: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_threshold_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    max_response_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=1048576)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # New alerts are created only after this many consecutive failed checks
    # (dedup bumps of an already-open alert are not gated).
    alert_after_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # TLS certificate expiry (https monitors only), refreshed at most daily.
    cert_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cert_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # up | down | unknown
    last_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown", index=True)
    last_response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    records: Mapped[list["MonitoringRecord"]] = relationship(
        "MonitoringRecord", back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )
    anomalies: Mapped[list["Anomaly"]] = relationship(
        "Anomaly", back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="monitor", cascade="all, delete-orphan", passive_deletes=True
    )
