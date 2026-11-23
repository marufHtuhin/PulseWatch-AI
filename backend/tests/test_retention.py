"""Data retention cleanup: old records (+ their anomalies) and old
resolved alerts are deleted; recent rows and active alerts are kept.
"""
from __future__ import annotations

from datetime import timedelta

from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitoring_record import MonitoringRecord
from app.scheduler import jobs
from app.services.retention_service import preview_cleanup, run_cleanup
from app.services.settings_service import get_or_create_settings
from app.utils.time import utcnow


def _seed_record(db, monitor_id, *, days_ago, success=True):
    record = MonitoringRecord(
        monitor_id=monitor_id,
        response_time_ms=100.0,
        status_code=200 if success else 500,
        response_size_bytes=100,
        records_returned=1,
        is_success=success,
        checked_at=utcnow() - timedelta(days=days_ago),
    )
    db.add(record)
    db.flush()
    return record


def _seed_anomaly(db, monitor_id, record_id, *, days_ago=0):
    anomaly = Anomaly(
        monitor_id=monitor_id,
        record_id=record_id,
        anomaly_type="HTTP_ERROR",
        severity="high",
        description="d",
        detected_at=utcnow() - timedelta(days=days_ago),
    )
    db.add(anomaly)
    db.flush()
    return anomaly


def _seed_alert(db, monitor_id, *, status, days_ago, anomaly_id=None,
                resolved_days_ago=None):
    alert = Alert(
        monitor_id=monitor_id,
        anomaly_id=anomaly_id,
        anomaly_type="HTTP_ERROR",
        title="t",
        severity="high",
        summary="s",
        possible_cause="c",
        recommended_action="a",
        status=status,
        ai_generated=False,
        occurrence_count=1,
        created_at=utcnow() - timedelta(days=days_ago),
        resolved_at=(
            utcnow() - timedelta(days=resolved_days_ago)
            if resolved_days_ago is not None
            else None
        ),
    )
    db.add(alert)
    db.flush()
    return alert


def _seed_scenario(db, make_monitor):
    """Old + recent records/alerts under the default windows
    (90d records, 365d alerts). Returns the ids to assert on."""
    monitor = make_monitor()

    old_record = _seed_record(db, monitor.id, days_ago=100)
    recent_record = _seed_record(db, monitor.id, days_ago=10)
    old_anomaly = _seed_anomaly(db, monitor.id, old_record.id, days_ago=100)
    recent_anomaly = _seed_anomaly(db, monitor.id, recent_record.id, days_ago=10)

    # Active alert pointing at the old record's anomaly: the alert must
    # survive cleanup, with its anomaly link nulled.
    active_alert = _seed_alert(
        db, monitor.id, status="active", days_ago=400, anomaly_id=old_anomaly.id
    )
    # Old resolved alert (resolved 400 days ago): deleted.
    old_resolved = _seed_alert(
        db, monitor.id, status="resolved", days_ago=400, resolved_days_ago=400
    )
    # Resolved long ago but with no resolved_at: falls back to created_at.
    old_resolved_no_ts = _seed_alert(db, monitor.id, status="resolved", days_ago=400)
    # Recently resolved: kept.
    recent_resolved = _seed_alert(
        db, monitor.id, status="resolved", days_ago=10, resolved_days_ago=10
    )
    db.commit()
    return {
        "monitor": monitor,
        "old_record": old_record.id,
        "recent_record": recent_record.id,
        "old_anomaly": old_anomaly.id,
        "recent_anomaly": recent_anomaly.id,
        "active_alert": active_alert.id,
        "old_resolved": old_resolved.id,
        "old_resolved_no_ts": old_resolved_no_ts.id,
        "recent_resolved": recent_resolved.id,
    }


def test_preview_returns_counts_without_deleting(db, make_monitor):
    ids = _seed_scenario(db, make_monitor)

    counts = preview_cleanup(db)

    assert counts == {
        "records_deleted": 1,  # the 100-day-old record
        "alerts_deleted": 2,  # both old resolved alerts
        "anomalies_deleted": 1,  # the anomaly tied to the old record
    }
    # Nothing was actually deleted.
    assert db.query(MonitoringRecord).count() == 2
    assert db.query(Anomaly).count() == 2
    assert db.query(Alert).count() == 4


def test_cleanup_deletes_old_and_keeps_recent(db, make_monitor):
    ids = _seed_scenario(db, make_monitor)

    counts = run_cleanup(db)

    assert counts == {
        "records_deleted": 1,
        "alerts_deleted": 2,
        "anomalies_deleted": 1,
    }
    db.expire_all()
    assert db.get(MonitoringRecord, ids["old_record"]) is None
    assert db.get(MonitoringRecord, ids["recent_record"]) is not None
    assert db.get(Anomaly, ids["old_anomaly"]) is None
    assert db.get(Anomaly, ids["recent_anomaly"]) is not None
    assert db.get(Alert, ids["old_resolved"]) is None
    assert db.get(Alert, ids["old_resolved_no_ts"]) is None
    assert db.get(Alert, ids["recent_resolved"]) is not None


def test_active_old_alerts_are_never_deleted(db, make_monitor):
    ids = _seed_scenario(db, make_monitor)

    run_cleanup(db)
    db.expire_all()

    alert = db.get(Alert, ids["active_alert"])
    assert alert is not None  # 400 days old but still active -> kept
    assert alert.anomaly_id is None  # ...its deleted anomaly unlinked


def test_cleanup_respects_custom_retention_days(db, make_monitor):
    monitor = make_monitor()
    _seed_record(db, monitor.id, days_ago=10)
    _seed_record(db, monitor.id, days_ago=3)
    db.commit()

    row = get_or_create_settings(db)
    row.retention_days = 7
    db.commit()

    counts = run_cleanup(db)
    assert counts["records_deleted"] == 1  # only the 10-day-old record
    assert db.query(MonitoringRecord).count() == 1


def test_cleanup_on_empty_database_returns_zeros(db):
    assert run_cleanup(db) == {
        "records_deleted": 0,
        "alerts_deleted": 0,
        "anomalies_deleted": 0,
    }
    assert preview_cleanup(db) == {
        "records_deleted": 0,
        "alerts_deleted": 0,
        "anomalies_deleted": 0,
    }


# --- API endpoints ----------------------------------------------------------

def test_cleanup_preview_endpoint_does_not_delete(client, db, make_monitor):
    _seed_scenario(db, make_monitor)

    response = client.get("/api/settings/cleanup-preview")
    assert response.status_code == 200
    assert response.json() == {
        "records_deleted": 1,
        "alerts_deleted": 2,
        "anomalies_deleted": 1,
    }
    assert db.query(MonitoringRecord).count() == 2  # untouched


def test_cleanup_endpoint_runs_now_and_returns_counts(client, db, make_monitor):
    _seed_scenario(db, make_monitor)

    response = client.post("/api/settings/cleanup")
    assert response.status_code == 200
    assert response.json() == {
        "records_deleted": 1,
        "alerts_deleted": 2,
        "anomalies_deleted": 1,
    }
    assert db.query(MonitoringRecord).count() == 1
    assert db.query(Alert).count() == 2  # active + recently resolved

    # A second run finds nothing left to delete.
    again = client.post("/api/settings/cleanup")
    assert again.json() == {
        "records_deleted": 0,
        "alerts_deleted": 0,
        "anomalies_deleted": 0,
    }


# --- scheduler job ----------------------------------------------------------

async def test_scheduled_cleanup_job_deletes_old_records(db, make_monitor):
    monitor = make_monitor()
    _seed_record(db, monitor.id, days_ago=100)
    _seed_record(db, monitor.id, days_ago=10)
    db.commit()

    await jobs.run_retention_cleanup()

    db.expire_all()
    assert db.query(MonitoringRecord).count() == 1
