"""MonitoringRecord / Anomaly / batch response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.monitoring_record import MonitoringRecord
from app.schemas.common import APIModel, UtcDateTime


class AnomalyOut(APIModel):
    id: int
    anomaly_type: str
    severity: str
    description: str
    detected_at: UtcDateTime


class MonitoringRecordBase(APIModel):
    id: int
    monitor_id: int
    response_time_ms: float | None
    status_code: int | None
    response_size_bytes: int
    records_returned: int | None
    is_success: bool
    error_message: str | None
    checked_at: UtcDateTime
    content_type: str | None
    is_valid_json: bool | None


class MonitoringRecordOut(MonitoringRecordBase):
    """Record with embedded anomalies (single-check and batch responses)."""

    anomalies: list[AnomalyOut] = []


class MonitoringRecordListOut(MonitoringRecordBase):
    """Record without anomalies (history lists stay light)."""


class CheckResponse(MonitoringRecordOut):
    """POST /api/monitors/{id}/check response."""

    alerts_created: list[int] = []


class BatchCheckRequest(BaseModel):
    monitor_ids: list[int] = Field(min_length=1, max_length=50)


class BatchCheckItem(BaseModel):
    monitor_id: int
    success: bool
    record: MonitoringRecordOut | None = None
    error: str | None = None


class BatchCheckResponse(BaseModel):
    results: list[BatchCheckItem]
    succeeded: int
    failed: int
    elapsed_ms: float


def record_to_response(record: MonitoringRecord) -> MonitoringRecordOut:
    return MonitoringRecordOut.model_validate(record)


def record_to_list_response(record: MonitoringRecord) -> MonitoringRecordListOut:
    return MonitoringRecordListOut.model_validate(record)
