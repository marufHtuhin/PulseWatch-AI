"""Consecutive-failure detection: a new alert is created only after the
monitor's threshold of consecutive failed checks, while anomalies are
still recorded on every failed check and dedup bumps are never gated.
"""
from __future__ import annotations

from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.services.monitoring_service import run_check
from tests.conftest import json_response_handler, mock_client_factory


async def _failing_check(db, monitor_id: int):
    factory = mock_client_factory(json_response_handler(status=500, payload={}))
    return await run_check(db, monitor_id, client_factory=factory)


async def _healthy_check(db, monitor_id: int):
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))
    return await run_check(db, monitor_id, client_factory=factory)


def _counter(db, monitor_id: int) -> int:
    db.expire_all()
    return db.get(Monitor, monitor_id).consecutive_failures


async def test_first_failure_with_threshold_2_records_anomaly_but_no_alert(
    db, make_monitor
):
    monitor = make_monitor(alert_after_failures=2)

    outcome = await _failing_check(db, monitor.id)

    assert outcome.record.is_success is False
    assert len(outcome.anomalies) == 1  # anomaly still recorded
    assert outcome.anomalies[0].anomaly_type == "HTTP_ERROR"
    assert outcome.alerts_created == []  # but no alert yet
    assert db.query(Alert).count() == 0
    assert _counter(db, monitor.id) == 1


async def test_second_consecutive_failure_creates_alert(db, make_monitor):
    monitor = make_monitor(alert_after_failures=2)

    first = await _failing_check(db, monitor.id)
    second = await _failing_check(db, monitor.id)

    assert first.alerts_created == []
    assert len(second.alerts_created) == 1
    assert _counter(db, monitor.id) == 2
    alert = db.query(Alert).first()
    assert alert.anomaly_type == "HTTP_ERROR"
    assert "Failed 2 consecutive checks." in alert.summary


async def test_success_between_failures_resets_the_counter(db, make_monitor):
    monitor = make_monitor(alert_after_failures=2)

    await _failing_check(db, monitor.id)
    assert _counter(db, monitor.id) == 1

    await _healthy_check(db, monitor.id)
    assert _counter(db, monitor.id) == 0  # reset by the success

    outcome = await _failing_check(db, monitor.id)
    assert outcome.alerts_created == []  # only 1 consecutive failure again
    assert db.query(Alert).count() == 0
    assert _counter(db, monitor.id) == 1


async def test_threshold_1_alerts_on_first_failure(db, make_monitor):
    monitor = make_monitor(alert_after_failures=1)

    outcome = await _failing_check(db, monitor.id)

    assert len(outcome.alerts_created) == 1
    assert "Failed 1 consecutive check." in db.query(Alert).first().summary


async def test_threshold_3_needs_three_failures(db, make_monitor):
    monitor = make_monitor(alert_after_failures=3)

    assert (await _failing_check(db, monitor.id)).alerts_created == []
    assert (await _failing_check(db, monitor.id)).alerts_created == []
    third = await _failing_check(db, monitor.id)
    assert len(third.alerts_created) == 1
    assert "Failed 3 consecutive checks." in db.query(Alert).first().summary


async def test_dedup_bump_still_happens_below_threshold(db, make_monitor):
    """The gate applies to creation only: once an alert is open, a failing
    check bumps it even when the counter is below the threshold."""
    monitor = make_monitor(alert_after_failures=2)

    await _failing_check(db, monitor.id)
    await _failing_check(db, monitor.id)  # alert created (2nd failure)
    assert db.query(Alert).first().occurrence_count == 1

    await _healthy_check(db, monitor.id)  # resets the counter to 0
    assert _counter(db, monitor.id) == 0

    outcome = await _failing_check(db, monitor.id)  # counter 1 < threshold 2
    assert outcome.alerts_created == []  # no NEW alert
    assert db.query(Alert).count() == 1  # still just the one alert
    assert db.query(Alert).first().occurrence_count == 2  # ...bumped


async def test_successful_check_alerts_are_not_gated(db, make_monitor):
    """A slow-but-successful check creates its alert immediately: the
    consecutive-failure counter is 0 on success by definition."""
    monitor = make_monitor(alert_after_failures=5, latency_threshold_ms=100)
    factory = mock_client_factory(json_response_handler(delay=0.12))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is True
    assert outcome.anomalies[0].anomaly_type == "HIGH_RESPONSE_TIME"
    assert len(outcome.alerts_created) == 1
    assert _counter(db, monitor.id) == 0


# --- API wiring -------------------------------------------------------------

def test_monitor_response_includes_failure_fields(client, create_monitor_via_api):
    created = create_monitor_via_api()
    # Defaults: threshold 2, zero consecutive failures so far.
    assert created["alert_after_failures"] == 2
    assert created["consecutive_failures"] == 0
    assert created["cert_expires_at"] is None
    assert created["cert_days_remaining"] is None


def test_monitor_create_and_update_accept_threshold(client, create_monitor_via_api):
    created = create_monitor_via_api(alert_after_failures=5)
    assert created["alert_after_failures"] == 5

    updated = client.put(
        f"/api/monitors/{created['id']}",
        json={**created, "alert_after_failures": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["alert_after_failures"] == 1


def test_monitor_threshold_validates_range(client):
    from tests.conftest import monitor_payload

    assert client.post(
        "/api/monitors", json=monitor_payload(alert_after_failures=0)
    ).status_code == 422
    assert client.post(
        "/api/monitors", json=monitor_payload(alert_after_failures=6)
    ).status_code == 422
