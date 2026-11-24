"""Admin endpoints: platform-wide user and monitor management.

Every endpoint requires ``require_admin`` (401 unauthenticated, 403
non-admin). Admins can list users and monitors, inspect one user,
activate/deactivate non-admin users, and hard-delete non-admin users
with all their data. Admins cannot deactivate or delete themselves or
another admin, and cannot change another user's password — those are
deliberately out of scope.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.logging import get_logger
from app.database.connection import get_db
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.models.password_reset_token import PasswordResetToken
from app.models.settings import AppSettings
from app.models.user import User
from app.scheduler.jobs import unschedule_monitor
from app.schemas.admin import (
    AdminMonitorOut,
    AdminStatsOut,
    AdminUserDetailOut,
    AdminUserMonitorOut,
    AdminUserOut,
    AdminUserUpdate,
)
from app.schemas.common import PaginatedResponse

logger = get_logger("api.admin")

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


def _monitor_ids(db: Session, user_id: int) -> list[int]:
    return [
        row[0]
        for row in db.query(Monitor.id).filter(Monitor.user_id == user_id).all()
    ]


def _alert_count(db: Session, monitor_ids: list[int]) -> int:
    if not monitor_ids:
        return 0
    return db.query(Alert).filter(Alert.monitor_id.in_(monitor_ids)).count()


def _user_summary(db: Session, user: User) -> AdminUserOut:
    monitor_ids = _monitor_ids(db, user.id)
    return AdminUserOut(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        created_at=user.created_at,
        monitor_count=len(monitor_ids),
        alert_count=_alert_count(db, monitor_ids),
    )


@router.get("/stats", response_model=AdminStatsOut)
def get_stats(db: Session = Depends(get_db)) -> AdminStatsOut:
    return AdminStatsOut(
        total_users=db.query(User).count(),
        total_monitors=db.query(Monitor).count(),
        active_monitors=db.query(Monitor).filter(Monitor.is_active.is_(True)).count(),
        total_alerts=db.query(Alert).count(),
        active_alerts=db.query(Alert).filter(Alert.status == "active").count(),
    )


@router.get("/users", response_model=PaginatedResponse[AdminUserOut])
def list_users(
    q: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AdminUserOut]:
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q}%"))
    total = query.count()
    users = query.order_by(User.id.asc()).offset(skip).limit(limit).all()
    return PaginatedResponse(
        items=[_user_summary(db, user) for user in users],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
def get_user(user_id: int, db: Session = Depends(get_db)) -> AdminUserDetailOut:
    user = _get_user_or_404(db, user_id)
    monitors = (
        db.query(Monitor)
        .filter(Monitor.user_id == user.id)
        .order_by(Monitor.id.asc())
        .all()
    )
    monitor_ids = [m.id for m in monitors]
    active_alert_count = 0
    if monitor_ids:
        active_alert_count = (
            db.query(Alert)
            .filter(
                Alert.monitor_id.in_(monitor_ids),
                Alert.status == "active",
            )
            .count()
        )
    return AdminUserDetailOut(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        created_at=user.created_at,
        monitor_count=len(monitors),
        alert_count=_alert_count(db, monitor_ids),
        active_alert_count=active_alert_count,
        monitors=[
            AdminUserMonitorOut(
                id=m.id,
                name=m.name,
                url=m.url,
                is_active=m.is_active,
                status=m.last_status,
            )
            for m in monitors
        ],
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminUserOut:
    user = _get_user_or_404(db, user_id)
    if user.id == current_admin.id and not payload.is_active:
        raise HTTPException(
            status_code=400, detail="Admins cannot deactivate themselves"
        )
    if user.is_admin and user.id != current_admin.id:
        raise HTTPException(
            status_code=400, detail="Admins cannot change another admin's status"
        )
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    logger.info(
        "admin user updated id=%s is_active=%s by admin_id=%s",
        user.id,
        user.is_active,
        current_admin.id,
    )
    return _user_summary(db, user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> Response:
    user = _get_user_or_404(db, user_id)
    if user.id == current_admin.id:
        raise HTTPException(
            status_code=400, detail="Admins cannot delete themselves"
        )
    if user.is_admin:
        raise HTTPException(
            status_code=400, detail="Admins cannot delete another admin"
        )
    monitor_ids = _monitor_ids(db, user.id)
    # Stop scheduled checks for this user's monitors first (no-op when
    # the scheduler is not running, e.g. under pytest).
    for monitor_id in monitor_ids:
        unschedule_monitor(monitor_id)
    # Explicit ordered deletes — do NOT rely on DB cascade: TiDB parses
    # FK DDL but does not enforce FKs, so orphaned rows would otherwise
    # survive. Within the monitor-owned rows, alerts go before anomalies
    # (alerts reference anomalies) and anomalies before records
    # (anomalies reference records).
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id
    ).delete(synchronize_session=False)
    if monitor_ids:
        db.query(Alert).filter(Alert.monitor_id.in_(monitor_ids)).delete(
            synchronize_session=False
        )
        db.query(Anomaly).filter(Anomaly.monitor_id.in_(monitor_ids)).delete(
            synchronize_session=False
        )
        db.query(MonitoringRecord).filter(
            MonitoringRecord.monitor_id.in_(monitor_ids)
        ).delete(synchronize_session=False)
    db.query(Monitor).filter(Monitor.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(AppSettings).filter(AppSettings.user_id == user.id).delete(
        synchronize_session=False
    )
    # Capture before deleting: the object is expired after commit and
    # its attributes can no longer be read.
    deleted_id, deleted_email = user.id, user.email
    db.delete(user)
    db.commit()
    logger.info(
        "admin user deleted id=%s email=%s by admin_id=%s",
        deleted_id,
        deleted_email,
        current_admin.id,
    )
    return Response(status_code=204)


@router.get("/monitors", response_model=PaginatedResponse[AdminMonitorOut])
def list_monitors(
    user_id: int | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AdminMonitorOut]:
    query = db.query(Monitor)
    if user_id is not None:
        query = query.filter(Monitor.user_id == user_id)
    total = query.count()
    monitors = query.order_by(Monitor.id.desc()).offset(skip).limit(limit).all()
    owner_ids = {m.user_id for m in monitors if m.user_id is not None}
    owners = {}
    if owner_ids:
        owners = {
            u.id: u.email
            for u in db.query(User).filter(User.id.in_(owner_ids)).all()
        }
    return PaginatedResponse(
        items=[
            AdminMonitorOut(
                id=m.id,
                name=m.name,
                url=m.url,
                is_active=m.is_active,
                status=m.last_status,
                user_id=m.user_id,
                owner_email=owners.get(m.user_id) if m.user_id is not None else None,
            )
            for m in monitors
        ],
        total=total,
        page=skip // limit + 1,
        page_size=limit,
    )
