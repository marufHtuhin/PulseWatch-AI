"""Alert creation + dedup.

Dedup rule (per contract): while an alert for (monitor_id, anomaly_type) is
``active`` or ``acknowledged``, a recurring same-type anomaly does NOT create
a new alert — it increments ``occurrence_count`` and updates ``last_seen_at``
(and points the alert at the newest anomaly). A new alert is created only
after the previous one is ``resolved``.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.services.ai_service import AIAlertContent
from app.utils.time import utcnow

OPEN_STATUSES = ("active", "acknowledged")


def find_open_alert(db: Session, monitor_id: int, anomaly_type: str) -> Alert | None:
    return (
        db.query(Alert)
        .filter(
            Alert.monitor_id == monitor_id,
            Alert.anomaly_type == anomaly_type,
            Alert.status.in_(OPEN_STATUSES),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )


def bump_alert(db: Session, alert: Alert, anomaly: Anomaly) -> Alert:
    alert.occurrence_count += 1
    alert.last_seen_at = utcnow()
    alert.anomaly_id = anomaly.id
    db.add(alert)
    return alert


def create_alert(
    db: Session,
    monitor: Monitor,
    anomaly: Anomaly,
    content: AIAlertContent,
    ai_generated: bool,
) -> Alert:
    now = utcnow()
    alert = Alert(
        monitor_id=monitor.id,
        anomaly_id=anomaly.id,
        anomaly_type=anomaly.anomaly_type,
        title=content.title,
        severity=content.severity,
        summary=content.summary,
        possible_cause=content.possible_cause,
        recommended_action=content.recommended_action,
        status="active",
        ai_generated=ai_generated,
        occurrence_count=1,
        last_seen_at=now,
        created_at=now,
    )
    db.add(alert)
    return alert
