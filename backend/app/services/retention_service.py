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
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitoring_record import MonitoringRecord
from app.models.settings import AppSettings
from app.utils.time import utcnow

logger = get_logger("retention")

DEFAULT_RETENTION_DAYS = 90
DEFAULT_ALERT_RETENTION_DAYS = 365


def _retention_windows(db: Session) -> tuple[timedelta, timedelta]:
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    retention = row.retention_days if row else DEFAULT_RETENTION_DAYS
    alert_retention = (
        row.alert_retention_days if row else DEFAULT_ALERT_RETENTION_DAYS
    )
    return timedelta(days=retention), timedelta(days=alert_retention)


def _counts(db: Session) -> dict[str, int]:
    now = utcnow()
    record_window, alert_window = _retention_windows(db)
    record_cutoff = now - record_window
    alert_cutoff = now - alert_window

    old_record_ids = select(MonitoringRecord.id).where(
        MonitoringRecord.checked_at < record_cutoff
    )
    anomalies = (
        db.query(Anomaly).filter(Anomaly.record_id.in_(old_record_ids)).count()
    )
    records = (
        db.query(MonitoringRecord)
        .filter(MonitoringRecord.checked_at < record_cutoff)
        .count()
    )
    alerts = (
        db.query(Alert)
        .filter(
            Alert.status == "resolved",
            (
                (Alert.resolved_at.isnot(None) & (Alert.resolved_at < alert_cutoff))
                | (
                    Alert.resolved_at.is_(None)
                    & (Alert.created_at < alert_cutoff)
                )
            ),
        )
        .count()
    )
    return {
        "records_deleted": records,
        "alerts_deleted": alerts,
        "anomalies_deleted": anomalies,
    }


def preview_cleanup(db: Session) -> dict[str, int]:
    """How many rows a cleanup would delete, without deleting anything."""
    return _counts(db)


def run_cleanup(db: Session) -> dict[str, int]:
    """Delete expired records (+ their anomalies) and old resolved alerts."""
    now = utcnow()
    record_window, alert_window = _retention_windows(db)
    record_cutoff = now - record_window
    alert_cutoff = now - alert_window

    old_record_ids = select(MonitoringRecord.id).where(
        MonitoringRecord.checked_at < record_cutoff
    )
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
        .filter(MonitoringRecord.checked_at < record_cutoff)
        .delete(synchronize_session=False)
    )
    alerts_deleted = (
        db.query(Alert)
        .filter(
            Alert.status == "resolved",
            (
                (Alert.resolved_at.isnot(None) & (Alert.resolved_at < alert_cutoff))
                | (
                    Alert.resolved_at.is_(None)
                    & (Alert.created_at < alert_cutoff)
                )
            ),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    counts = {
        "records_deleted": records_deleted,
        "alerts_deleted": alerts_deleted,
        "anomalies_deleted": anomalies_deleted,
    }
    logger.info(
        "retention cleanup done records=%s alerts=%s anomalies=%s",
        counts["records_deleted"],
        counts["alerts_deleted"],
        counts["anomalies_deleted"],
    )
    return counts
