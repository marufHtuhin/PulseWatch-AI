"""Data retention cleanup.

- MonitoringRecords older than ``retention_days`` are deleted, together
  with the anomalies tied to them (deleted explicitly first — never
  relying on FK cascades, which SQLite may not enforce and some MySQL
  variants ignore). Alerts pointing at a deleted anomaly get their
  ``anomaly_id`` nulled first, for the same reason.
- Resolved alerts older than ``alert_retention_days`` are deleted
  (``resolved_at`` when set, else ``created_at``). Active and
  acknowledged alerts are never deleted, however old.
- ``preview_cleanup`` returns the same counts without deleting anything
  (and without creating the settings row).

Multi-user scoping: each user's own retention windows (from their
settings row; defaults 90/365 when they have no row) apply to their own
records/alerts only. Ownerless data (monitors with ``user_id`` NULL) uses
the defaults. ``run_cleanup(db)`` / ``preview_cleanup(db)`` with no
``user_id`` — the scheduler path — clean every owner's data with that
owner's windows; the settings API passes the current user's id.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.services.settings_service import get_settings_row
from app.utils.time import utcnow

logger = get_logger("retention")

DEFAULT_RETENTION_DAYS = 90
DEFAULT_ALERT_RETENTION_DAYS = 365


def _retention_windows(db: Session, user_id: int | None) -> tuple[timedelta, timedelta]:
    row = get_settings_row(db, user_id)
    retention = row.retention_days if row else DEFAULT_RETENTION_DAYS
    alert_retention = (
        row.alert_retention_days if row else DEFAULT_ALERT_RETENTION_DAYS
    )
    return timedelta(days=retention), timedelta(days=alert_retention)


def _owner_clause(user_id: int | None):
    """The Monitor filter for one owner (NULL = ownerless monitors)."""
    if user_id is None:
        return Monitor.user_id.is_(None)
    return Monitor.user_id == user_id


def _old_record_ids(db: Session, user_id: int | None, record_cutoff):  # noqa: ANN001, ANN202
    """IDs of one owner's records older than the cutoff (a SELECT, so it
    can be reused by the anomaly/record/alert queries below)."""
    return (
        select(MonitoringRecord.id)
        .join(Monitor, MonitoringRecord.monitor_id == Monitor.id)
        .where(
            _owner_clause(user_id),
            MonitoringRecord.checked_at < record_cutoff,
        )
    )


def _resolved_alert_cutoff(alert_cutoff):  # noqa: ANN001, ANN202
    """Resolved alerts older than the cutoff (``resolved_at`` when set,
    else ``created_at``)."""
    return (
        (Alert.resolved_at.isnot(None) & (Alert.resolved_at < alert_cutoff))
        | (Alert.resolved_at.is_(None) & (Alert.created_at < alert_cutoff))
    )


def _old_alert_ids(db: Session, user_id: int | None, alert_cutoff):  # noqa: ANN001, ANN202
    """IDs of one owner's resolved alerts older than the cutoff."""
    return (
        select(Alert.id)
        .join(Monitor, Alert.monitor_id == Monitor.id)
        .where(
            _owner_clause(user_id),
            Alert.status == "resolved",
            _resolved_alert_cutoff(alert_cutoff),
        )
    )


def _counts_for_owner(db: Session, user_id: int | None, now) -> dict[str, int]:  # noqa: ANN001
    record_window, alert_window = _retention_windows(db, user_id)
    old_record_ids = _old_record_ids(db, user_id, now - record_window)
    old_alert_ids = _old_alert_ids(db, user_id, now - alert_window)
    return {
        "records_deleted": (
            db.query(MonitoringRecord)
            .filter(MonitoringRecord.id.in_(old_record_ids))
            .count()
        ),
        "alerts_deleted": (
            db.query(Alert).filter(Alert.id.in_(old_alert_ids)).count()
        ),
        "anomalies_deleted": (
            db.query(Anomaly)
            .filter(Anomaly.record_id.in_(old_record_ids))
            .count()
        ),
    }


def _delete_for_owner(db: Session, user_id: int | None, now) -> dict[str, int]:  # noqa: ANN001
    record_window, alert_window = _retention_windows(db, user_id)
    old_record_ids = _old_record_ids(db, user_id, now - record_window)
    old_alert_ids = _old_alert_ids(db, user_id, now - alert_window)
    old_anomaly_ids = select(Anomaly.id).where(
        Anomaly.record_id.in_(old_record_ids)
    )
    # Alerts reference anomalies via anomaly_id (SET NULL on delete where FKs
    # are enforced); null them explicitly so the delete is safe everywhere.
    db.query(Alert).filter(Alert.anomaly_id.in_(old_anomaly_ids)).update(
        {Alert.anomaly_id: None}, synchronize_session=False
    )
    anomalies_deleted = (
        db.query(Anomaly)
        .filter(Anomaly.record_id.in_(old_record_ids))
        .delete(synchronize_session=False)
    )
    records_deleted = (
        db.query(MonitoringRecord)
        .filter(MonitoringRecord.id.in_(old_record_ids))
        .delete(synchronize_session=False)
    )
    alerts_deleted = (
        db.query(Alert)
        .filter(Alert.id.in_(old_alert_ids))
        .delete(synchronize_session=False)
    )
    return {
        "records_deleted": records_deleted,
        "alerts_deleted": alerts_deleted,
        "anomalies_deleted": anomalies_deleted,
    }


def _owner_scopes(db: Session) -> list[int | None]:
    """Every monitor owner (user ids, plus None for ownerless monitors)."""
    return [row[0] for row in db.query(Monitor.user_id).distinct().all()]


def _sum(counts_list: list[dict[str, int]]) -> dict[str, int]:
    totals = {"records_deleted": 0, "alerts_deleted": 0, "anomalies_deleted": 0}
    for counts in counts_list:
        for key in totals:
            totals[key] += counts[key]
    return totals


def preview_cleanup(db: Session, user_id: int | None = None) -> dict[str, int]:
    """How many rows a cleanup would delete, without deleting anything.

    With ``user_id``: only that user's data, with their windows. Without:
    every owner's data, each with that owner's windows (scheduler path).
    """
    now = utcnow()
    if user_id is not None:
        return _counts_for_owner(db, user_id, now)
    return _sum(_counts_for_owner(db, owner, now) for owner in _owner_scopes(db))


def run_cleanup(db: Session, user_id: int | None = None) -> dict[str, int]:
    """Delete expired records (+ their anomalies) and old resolved alerts.

    Same scoping as ``preview_cleanup``; one commit for the whole run.
    """
    now = utcnow()
    owners = [user_id] if user_id is not None else _owner_scopes(db)
    counts = _sum(_delete_for_owner(db, owner, now) for owner in owners)
    db.commit()
    logger.info(
        "retention cleanup done records=%s alerts=%s anomalies=%s",
        counts["records_deleted"],
        counts["alerts_deleted"],
        counts["anomalies_deleted"],
    )
    return counts
