"""Dashboard endpoints: summary, performance, per-monitor health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.schemas.dashboard import DashboardSummary, HealthResponse, PerformanceResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(db: Session = Depends(get_db)) -> DashboardSummary:
    return dashboard_service.get_summary(db)


@router.get("/performance", response_model=PerformanceResponse)
def performance(
    monitor_id: int | None = None,
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
) -> PerformanceResponse:
    return dashboard_service.get_performance(db, monitor_id=monitor_id, hours=hours)


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    return dashboard_service.get_health(db)
