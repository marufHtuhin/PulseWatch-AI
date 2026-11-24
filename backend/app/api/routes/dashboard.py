"""Dashboard endpoints: summary, performance, per-monitor health.

All endpoints require authentication and are scoped to the current user's
monitors; a ``monitor_id`` belonging to another user is a 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.database.connection import get_db
from app.models.monitor import Monitor
from app.models.user import User
from app.schemas.dashboard import DashboardSummary, HealthResponse, PerformanceResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummary:
    return dashboard_service.get_summary(db, user_id=current_user.id)


@router.get("/performance", response_model=PerformanceResponse)
def performance(
    monitor_id: int | None = None,
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceResponse:
    if monitor_id is not None:
        monitor = (
            db.query(Monitor)
            .filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id)
            .first()
        )
        if monitor is None:
            raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")
    return dashboard_service.get_performance(
        db, monitor_id=monitor_id, hours=hours, user_id=current_user.id
    )


@router.get("/health", response_model=HealthResponse)
def health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> HealthResponse:
    return dashboard_service.get_health(db, user_id=current_user.id)
