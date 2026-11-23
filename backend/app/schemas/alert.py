"""Alert response schemas."""
from __future__ import annotations

from app.models.alert import Alert
from app.schemas.common import APIModel, UtcDateTime


class AlertOut(APIModel):
    id: int
    monitor_id: int
    monitor_name: str
    anomaly_id: int | None
    anomaly_type: str
    title: str
    severity: str
    summary: str
    possible_cause: str
    recommended_action: str
    status: str
    ai_generated: bool
    occurrence_count: int
    last_seen_at: UtcDateTime
    created_at: UtcDateTime
    acknowledged_at: UtcDateTime | None = None
    resolved_at: UtcDateTime | None = None


class AlertMonitorInfo(APIModel):
    name: str
    url: str
    method: str


class AlertAnomalyInfo(APIModel):
    id: int
    anomaly_type: str
    severity: str
    description: str
    detected_at: UtcDateTime


class AlertRecordInfo(APIModel):
    id: int
    response_time_ms: float | None
    status_code: int | None
    response_size_bytes: int
    records_returned: int | None
    is_success: bool
    error_message: str | None
    checked_at: UtcDateTime
    content_type: str | None
    is_valid_json: bool | None


class AlertDetailOut(AlertOut):
    monitor: AlertMonitorInfo | None = None
    anomaly: AlertAnomalyInfo | None = None
    record: AlertRecordInfo | None = None


def alert_to_response(alert: Alert) -> AlertOut:
    data = {c.key: getattr(alert, c.key) for c in alert.__table__.columns}
    data["monitor_name"] = alert.monitor.name if alert.monitor is not None else ""
    return AlertOut.model_validate(data)
