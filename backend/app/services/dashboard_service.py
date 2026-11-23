"""Dashboard aggregations — all computed from real stored data."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.schemas.dashboard import (
    DashboardSummary,
    HealthResponse,
    MonitorHealthItem,
    PerformancePoint,
    PerformanceResponse,
)
from app.utils.time import utcnow

MAX_PERFORMANCE_POINTS = 200


def get_summary(db: Session) -> DashboardSummary:
    now = utcnow()
    day_ago = now - timedelta(hours=24)

    total = db.query(func.count(Monitor.id)).scalar() or 0
    active = (
        db.query(func.count(Monitor.id)).filter(Monitor.is_active.is_(True)).scalar() or 0
    )
    healthy = (
        db.query(func.count(Monitor.id)).filter(Monitor.last_status == "up").scalar() or 0
    )
    unhealthy = (
        db.query(func.count(Monitor.id)).filter(Monitor.last_status == "down").scalar() or 0
    )
    unknown = (
        db.query(func.count(Monitor.id)).filter(Monitor.last_status == "unknown").scalar()
        or 0
    )
    active_alerts = (
        db.query(func.count(Alert.id)).filter(Alert.status == "active").scalar() or 0
    )
    critical_alerts = (
        db.query(func.count(Alert.id))
        .filter(Alert.status == "active", Alert.severity == "critical")
        .scalar()
        or 0
    )
    total_checks_24h = (
        db.query(func.count(MonitoringRecord.id))
        .filter(MonitoringRecord.checked_at >= day_ago)
        .scalar()
        or 0
    )
    failed_checks_24h = (
        db.query(func.count(MonitoringRecord.id))
        .filter(
            MonitoringRecord.checked_at >= day_ago,
            MonitoringRecord.is_success.is_(False),
        )
        .scalar()
        or 0
    )
    if total_checks_24h == 0:
        overall_uptime_pct = 100.0
    else:
        overall_uptime_pct = round(
            (total_checks_24h - failed_checks_24h) / total_checks_24h * 100, 1
        )
    avg_rt = (
        db.query(func.avg(MonitoringRecord.response_time_ms))
        .filter(
            MonitoringRecord.checked_at >= day_ago,
            MonitoringRecord.response_time_ms.isnot(None),
        )
        .scalar()
    )
    return DashboardSummary(
        total_monitors=total,
        active_monitors=active,
        healthy_monitors=healthy,
        unhealthy_monitors=unhealthy,
        unknown_monitors=unknown,
        active_alerts=active_alerts,
        critical_alerts=critical_alerts,
        overall_uptime_pct=overall_uptime_pct,
        avg_response_time_ms=round(float(avg_rt), 1) if avg_rt is not None else 0.0,
        total_checks_24h=total_checks_24h,
        failed_checks_24h=failed_checks_24h,
    )


def get_performance(
    db: Session, monitor_id: int | None = None, hours: int = 24
) -> PerformanceResponse:
    cutoff = utcnow() - timedelta(hours=hours)
    query = (
        db.query(MonitoringRecord, Monitor.name)
        .join(Monitor, MonitoringRecord.monitor_id == Monitor.id)
        .filter(MonitoringRecord.checked_at >= cutoff)
    )
    if monitor_id is not None:
        query = query.filter(MonitoringRecord.monitor_id == monitor_id)
    rows = query.order_by(MonitoringRecord.checked_at.asc()).all()

    # Bucket down to at most ~200 points by even sampling.
    if len(rows) > MAX_PERFORMANCE_POINTS:
        step = len(rows) / MAX_PERFORMANCE_POINTS
        rows = [rows[int(i * step)] for i in range(MAX_PERFORMANCE_POINTS)]

    points = [
        PerformancePoint(
            time=record.checked_at,
            monitor_id=record.monitor_id,
            monitor_name=name,
            response_time_ms=record.response_time_ms,
            status_code=record.status_code,
            is_success=record.is_success,
        )
        for record, name in rows
    ]
    return PerformanceResponse(points=points)


def get_health(db: Session) -> HealthResponse:
    day_ago = utcnow() - timedelta(hours=24)
    monitors = db.query(Monitor).order_by(Monitor.id.asc()).all()
    items: list[MonitorHealthItem] = []
    for monitor in monitors:
        base = db.query(MonitoringRecord).filter(
            MonitoringRecord.monitor_id == monitor.id,
            MonitoringRecord.checked_at >= day_ago,
        )
        total = base.count()
        failed = base.filter(MonitoringRecord.is_success.is_(False)).count()
        uptime_pct = 100.0 if total == 0 else round((total - failed) / total * 100, 1)
        avg_rt = (
            db.query(func.avg(MonitoringRecord.response_time_ms))
            .filter(
                MonitoringRecord.monitor_id == monitor.id,
                MonitoringRecord.checked_at >= day_ago,
                MonitoringRecord.response_time_ms.isnot(None),
            )
            .scalar()
        )
        active_alerts = (
            db.query(func.count(Alert.id))
            .filter(Alert.monitor_id == monitor.id, Alert.status == "active")
            .scalar()
            or 0
        )
        items.append(
            MonitorHealthItem(
                monitor_id=monitor.id,
                name=monitor.name,
                status=monitor.last_status,
                uptime_pct=uptime_pct,
                avg_response_time_ms=round(float(avg_rt), 1) if avg_rt is not None else 0.0,
                last_status_code=monitor.last_status_code,
                last_checked_at=monitor.last_checked_at,
                active_alerts=active_alerts,
            )
        )
    return HealthResponse(monitors=items)
