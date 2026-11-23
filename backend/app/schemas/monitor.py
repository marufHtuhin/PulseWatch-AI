"""Monitor request/response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.core.security import mask_headers
from app.models.monitor import Monitor
from app.schemas.common import APIModel, UtcDateTime
from app.utils.time import to_naive_utc, utcnow

Method = Literal["GET", "POST", "PUT", "DELETE"]
IntervalSeconds = Literal[30, 60, 300, 900, 1800]


class MonitorBase(APIModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    method: Method = "GET"
    headers: dict[str, str] | None = None
    request_body: str | None = None
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    interval_seconds: IntervalSeconds = 300
    expected_status_codes: list[int] = Field(default_factory=lambda: [200])
    expected_fields: list[str] = Field(default_factory=list)
    check_zero_records: bool = False
    latency_threshold_ms: int = Field(default=3000, ge=1)
    max_response_size_bytes: int = Field(default=1048576, ge=1)
    is_active: bool = True
    # A new alert is created only after this many consecutive failed checks.
    alert_after_failures: int = Field(default=2, ge=1, le=5)

    @field_validator("url")
    @classmethod
    def _validate_url_format(cls, value: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(value.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("url must be a valid http(s) URL")
        return value.strip()

    @field_validator("expected_status_codes")
    @classmethod
    def _validate_status_codes(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("expected_status_codes must not be empty")
        for code in value:
            if not 100 <= code <= 599:
                raise ValueError(f"invalid HTTP status code: {code}")
        return value


class MonitorCreate(MonitorBase):
    """POST /api/monitors body."""


class MonitorUpdate(MonitorBase):
    """PUT /api/monitors/{id} body — full update, same fields as create.

    A secret header sent as "********" keeps the stored value.
    """


class MonitorResponse(MonitorBase):
    id: int
    created_at: UtcDateTime
    updated_at: UtcDateTime
    last_checked_at: UtcDateTime | None = None
    last_status: str = "unknown"
    last_response_time_ms: float | None = None
    last_status_code: int | None = None
    consecutive_failures: int = 0
    cert_expires_at: UtcDateTime | None = None
    # Computed from cert_expires_at (not a column); None when no expiry is
    # stored. Negative when the certificate has already expired.
    cert_days_remaining: float | None = None


def cert_days_remaining(expires_at: datetime | None) -> float | None:
    """Fractional days until the stored cert expiry, or None if unknown."""
    if expires_at is None:
        return None
    delta = to_naive_utc(expires_at) - to_naive_utc(utcnow())
    return round(delta.total_seconds() / 86400, 1)


def monitor_to_response(monitor: Monitor) -> MonitorResponse:
    """Build a response with secret header values masked.

    Extra table columns (e.g. cert_checked_at) are ignored by the schema —
    APIModel uses Pydantic's default extra='ignore'.
    """
    data = {c.key: getattr(monitor, c.key) for c in monitor.__table__.columns}
    data["headers"] = mask_headers(monitor.headers)
    data["cert_days_remaining"] = cert_days_remaining(monitor.cert_expires_at)
    return MonitorResponse.model_validate(data)
