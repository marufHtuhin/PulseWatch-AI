"""Monitoring history + batch check endpoints.

All endpoints require authentication and are scoped to the current user
(history joins the monitor to enforce ownership; batch checks silently
skip ids the user does not own).
"""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.database.connection import SessionLocal, get_db
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.record import (
    BatchCheckItem,
    BatchCheckRequest,
    BatchCheckResponse,
    MonitoringRecordListOut,
    record_to_list_response,
)
from app.services.monitoring_service import run_batch_checks
from app.services.settings_service import get_effective_max_concurrency

logger = get_logger("api.monitoring")

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _history_query(
    db: Session,
    user_id: int,
    monitor_id: int | None,
    is_success: bool | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
):
    query = (
        db.query(MonitoringRecord)
        .join(Monitor, MonitoringRecord.monitor_id == Monitor.id)
        .filter(Monitor.user_id == user_id)
    )
    if monitor_id is not None:
        query = query.filter(MonitoringRecord.monitor_id == monitor_id)
    if is_success is not None:
        query = query.filter(MonitoringRecord.is_success == is_success)
    if from_dt is not None:
        query = query.filter(MonitoringRecord.checked_at >= from_dt)
    if to_dt is not None:
        query = query.filter(MonitoringRecord.checked_at <= to_dt)
    return query.order_by(MonitoringRecord.checked_at.desc())


def _paginate(query, page: int, page_size: int) -> PaginatedResponse[MonitoringRecordListOut]:
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        items=[record_to_list_response(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def _owned_monitor_or_404(db: Session, monitor_id: int, user_id: int) -> None:
    """404 unless the monitor exists AND belongs to this user."""
    monitor = (
        db.query(Monitor)
        .filter(Monitor.id == monitor_id, Monitor.user_id == user_id)
        .first()
    )
    if monitor is None:
        raise HTTPException(status_code=404, detail=f"Monitor {monitor_id} not found")


@router.get("/history", response_model=PaginatedResponse[MonitoringRecordListOut])
def list_history(
    monitor_id: int | None = None,
    is_success: bool | None = None,
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[MonitoringRecordListOut]:
    if monitor_id is not None:
        _owned_monitor_or_404(db, monitor_id, current_user.id)
    return _paginate(
        _history_query(db, current_user.id, monitor_id, is_success, from_dt, to_dt),
        page,
        page_size,
    )


@router.get("/history/{monitor_id}", response_model=PaginatedResponse[MonitoringRecordListOut])
def list_history_for_monitor(
    monitor_id: int,
    is_success: bool | None = None,
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[MonitoringRecordListOut]:
    _owned_monitor_or_404(db, monitor_id, current_user.id)
    return _paginate(
        _history_query(db, current_user.id, monitor_id, is_success, from_dt, to_dt),
        page,
        page_size,
    )


@router.post("/batch", response_model=BatchCheckResponse)
async def batch_check(
    payload: BatchCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchCheckResponse:
    if len(payload.monitor_ids) > settings.MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"At most {settings.MAX_BATCH_SIZE} monitors per batch",
        )
    # Dedupe, preserving order — then keep only the monitors this user
    # owns. Ids belonging to other users (or not existing) are silently
    # skipped: they simply do not appear in the results.
    monitor_ids = list(dict.fromkeys(payload.monitor_ids))
    owned_ids = {
        row[0]
        for row in db.query(Monitor.id)
        .filter(
            Monitor.id.in_(monitor_ids),
            Monitor.user_id == current_user.id,
        )
        .all()
    }
    monitor_ids = [mid for mid in monitor_ids if mid in owned_ids]
    max_concurrency = get_effective_max_concurrency(db, current_user.id)
    logger.info(
        "batch check started monitors=%s max_concurrency=%s user_id=%s",
        len(monitor_ids),
        max_concurrency,
        current_user.id,
    )
    started_at = time.perf_counter()
    results = await run_batch_checks(SessionLocal, monitor_ids, max_concurrency)
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    succeeded = sum(1 for r in results if r.success)
    return BatchCheckResponse(
        results=[
            BatchCheckItem(
                monitor_id=r.monitor_id,
                success=r.success,
                record=r.record,
                error=r.error,
            )
            for r in results
        ],
        succeeded=succeeded,
        failed=len(results) - succeeded,
        elapsed_ms=elapsed_ms,
    )
