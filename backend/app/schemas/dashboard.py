"""Dashboard response schemas."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import UtcDateTime


class DashboardSummary(BaseModel):
    total_monitors: int
    active_monitors: int
    healthy_monitors: int
    unhealthy_monitors: int
    unknown_monitors: int
    active_alerts: int
    critical_alerts: int
    overall_uptime_pct: float
    avg_response_time_ms: float
    total_checks_24h: int
    failed_checks_24h: int
    # Latency percentiles over successful checks in the last 24h.
    # Null when there is no data — never 0.
    p50_response_time_ms: float | None = None
    p95_response_time_ms: float | None = None
    p99_response_time_ms: float | None = None


class PerformancePoint(BaseModel):
    time: UtcDateTime
    monitor_id: int
    monitor_name: str
    response_time_ms: float | None
    status_code: int | None
    is_success: bool


class PerformanceResponse(BaseModel):
    points: list[PerformancePoint]


class MonitorHealthItem(BaseModel):
    monitor_id: int
    name: str
    status: str
    uptime_pct: float
    avg_response_time_ms: float
    # p95 over the monitor's successful checks in the last 24h (null: no data).
    p95_response_time_ms: float | None = None
    last_status_code: int | None
    last_checked_at: UtcDateTime | None
    active_alerts: int


class HealthResponse(BaseModel):
    monitors: list[MonitorHealthItem]
