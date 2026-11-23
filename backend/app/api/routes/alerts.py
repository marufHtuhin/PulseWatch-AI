"""Alert list/detail/lifecycle endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.connection import get_db
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitoring_record import MonitoringRecord
from app.schemas.alert import (
    AlertAnomalyInfo,
    AlertDetailOut,
    AlertMonitorInfo,
    AlertOut,
    AlertRecordInfo,
    alert_to_response,
)
from app.schemas.common import PaginatedResponse
from app.utils.time import utcnow

logger = get_logger("api.alerts")

router = APIRouter(prefix="/alerts", tags=["alerts"])

Severity = Literal["info", "warning", "high", "critical"]
AlertStatus = Literal["active", "acknowledged", "resolved"]


def _filtered_query(
    db: Session,
    severity: str | None,
    status: str | None,
    monitor_id: int | None,
    search: str | None,
):
    query = db.query(Alert)
    if severity is not None:
        query = query.filter(Alert.severity == severity)
    if status is not None:
        query = query.filter(Alert.status == status)
    if monitor_id is not None:
        query = query.filter(Alert.monitor_id == monitor_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(Alert.title.ilike(pattern), Alert.summary.ilike(pattern))
        )
    return query.order_by(Alert.created_at.desc())


def _paginate(query, page: int, page_size: int) -> PaginatedResponse[AlertOut]:
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        items=[alert_to_response(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=PaginatedResponse[AlertOut])
def list_alerts(
    severity: Severity | None = None,
    status: AlertStatus | None = None,
    monitor_id: int | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AlertOut]:
    return _paginate(
        _filtered_query(db, severity, status, monitor_id, search), page, page_size
    )


@router.get("/history", response_model=PaginatedResponse[AlertOut])
def list_alert_history(
    severity: Severity | None = None,
    monitor_id: int | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AlertOut]:
    """Resolved alerts only; same filters as the main list."""
    return _paginate(
        _filtered_query(db, severity, "resolved", monitor_id, search), page, page_size
    )


def _get_alert_or_404(db: Session, alert_id: int) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return alert


@router.get("/{alert_id}", response_model=AlertDetailOut)
def get_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertDetailOut:
    alert = _get_alert_or_404(db, alert_id)
    base = alert_to_response(alert).model_dump()
    monitor = alert.monitor
    anomaly = db.get(Anomaly, alert.anomaly_id) if alert.anomaly_id else None
    record = (
        db.get(MonitoringRecord, anomaly.record_id)
        if anomaly is not None
        else None
    )
    return AlertDetailOut(
        **base,
        monitor=(
            AlertMonitorInfo(name=monitor.name, url=monitor.url, method=monitor.method)
            if monitor is not None
            else None
        ),
        anomaly=AlertAnomalyInfo.model_validate(anomaly) if anomaly is not None else None,
        record=AlertRecordInfo.model_validate(record) if record is not None else None,
    )


@router.patch("/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertOut:
    alert = _get_alert_or_404(db, alert_id)
    if alert.status == "resolved":
        raise HTTPException(
            status_code=400, detail="Cannot acknowledge a resolved alert"
        )
    if alert.status == "active":
        alert.status = "acknowledged"
        alert.acknowledged_at = utcnow()
        db.commit()
        db.refresh(alert)
        logger.info("alert acknowledged id=%s", alert.id)
    return alert_to_response(alert)


@router.patch("/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertOut:
    alert = _get_alert_or_404(db, alert_id)
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_at = utcnow()
        db.commit()
        db.refresh(alert)
        logger.info("alert resolved id=%s", alert.id)
    return alert_to_response(alert)
