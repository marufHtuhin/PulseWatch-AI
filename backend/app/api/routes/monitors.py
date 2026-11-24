"""Monitor CRUD + manual check endpoints.

All endpoints require authentication and are scoped to the current user:
a monitor owned by another user behaves exactly as if it did not exist
(404, never 403 — no cross-user information leak).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.logging import get_logger
from app.core.security import merge_headers
from app.database.connection import get_db
from app.models.monitor import Monitor
from app.models.user import User
from app.scheduler.jobs import reschedule_monitor, unschedule_monitor
from app.schemas.common import PaginatedResponse
from app.schemas.monitor import (
    MonitorCreate,
    MonitorResponse,
    MonitorUpdate,
    monitor_to_response,
)
from app.schemas.record import CheckResponse, record_to_response
from app.services.monitoring_service import MonitorNotFoundError, run_check

logger = get_logger("api.monitors")

router = APIRouter(prefix="/monitors", tags=["monitors"])


def _get_monitor_or_404(db: Session, monitor_id: int, user_id: int) -> Monitor:
    """The monitor, only if it belongs to this user — another user's
    monitor (or a missing one) is a 404."""
    monitor = (
        db.query(Monitor)
        .filter(Monitor.id == monitor_id, Monitor.user_id == user_id)
        .first()
    )
    if monitor is None:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return monitor


@router.post("", response_model=MonitorResponse, status_code=201)
def create_monitor(
    payload: MonitorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MonitorResponse:
    monitor = Monitor(**payload.model_dump(), user_id=current_user.id)
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    reschedule_monitor(monitor)
    logger.info(
        "monitor created id=%s name=%s user_id=%s",
        monitor.id,
        monitor.name,
        current_user.id,
    )
    return monitor_to_response(monitor)


@router.get("", response_model=PaginatedResponse[MonitorResponse])
def list_monitors(
    search: str | None = None,
    is_active: bool | None = None,
    status: Literal["up", "down", "unknown"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[MonitorResponse]:
    query = db.query(Monitor).filter(Monitor.user_id == current_user.id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Monitor.name.ilike(pattern), Monitor.url.ilike(pattern)))
    if is_active is not None:
        query = query.filter(Monitor.is_active == is_active)
    if status is not None:
        query = query.filter(Monitor.last_status == status)
    total = query.count()
    items = (
        query.order_by(Monitor.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        items=[monitor_to_response(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{monitor_id}", response_model=MonitorResponse)
def get_monitor(
    monitor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MonitorResponse:
    return monitor_to_response(_get_monitor_or_404(db, monitor_id, current_user.id))


@router.put("/{monitor_id}", response_model=MonitorResponse)
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MonitorResponse:
    monitor = _get_monitor_or_404(db, monitor_id, current_user.id)
    data = payload.model_dump()
    # "********" on a secret header keeps the stored value.
    data["headers"] = merge_headers(monitor.headers, payload.headers)
    for key, value in data.items():
        setattr(monitor, key, value)
    db.commit()
    db.refresh(monitor)
    reschedule_monitor(monitor)
    logger.info("monitor updated id=%s name=%s", monitor.id, monitor.name)
    return monitor_to_response(monitor)


@router.patch("/{monitor_id}/toggle", response_model=MonitorResponse)
def toggle_monitor(
    monitor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MonitorResponse:
    monitor = _get_monitor_or_404(db, monitor_id, current_user.id)
    monitor.is_active = not monitor.is_active
    db.commit()
    db.refresh(monitor)
    reschedule_monitor(monitor)
    logger.info(
        "monitor toggled id=%s is_active=%s", monitor.id, monitor.is_active
    )
    return monitor_to_response(monitor)


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(
    monitor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    monitor = _get_monitor_or_404(db, monitor_id, current_user.id)
    unschedule_monitor(monitor.id)
    db.delete(monitor)  # cascades records / anomalies / alerts
    db.commit()
    logger.info("monitor deleted id=%s name=%s", monitor.id, monitor.name)
    return Response(status_code=204)


@router.post("/{monitor_id}/check", response_model=CheckResponse)
async def check_monitor(
    monitor_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CheckResponse:
    # Ownership check first: another user's monitor must 404 without
    # running (or leaking) a check.
    _get_monitor_or_404(db, monitor_id, current_user.id)
    try:
        outcome = await run_check(db, monitor_id)
    except MonitorNotFoundError:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    record_data = record_to_response(outcome.record).model_dump()
    return CheckResponse(**record_data, alerts_created=outcome.alerts_created)
