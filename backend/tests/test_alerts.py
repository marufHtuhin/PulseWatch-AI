"""Alerts: creation on anomaly, dedup, acknowledge/resolve, filters, history."""
from __future__ import annotations

from app.models.alert import Alert
from app.services.monitoring_service import run_check
from tests.conftest import json_response_handler, mock_client_factory


async def _failing_check(db, monitor_id: int):
    """One check that always produces an HTTP_ERROR anomaly + alert."""
    factory = mock_client_factory(json_response_handler(status=500, payload={}))
    return await run_check(db, monitor_id, client_factory=factory)


async def test_alert_created_on_anomaly_with_fallback_content(db, make_monitor):
    monitor = make_monitor(name="Flaky API")
    outcome = await _failing_check(db, monitor.id)

    assert len(outcome.alerts_created) == 1
    alert = db.query(Alert).first()
    assert alert is not None
    assert alert.monitor_id == monitor.id
    assert alert.anomaly_type == "HTTP_ERROR"
    assert alert.severity == "high"
    assert alert.status == "active"
    assert alert.occurrence_count == 1
    assert alert.ai_generated is False  # no Gemini key -> deterministic fallback
    assert "Flaky API" in alert.title
    assert alert.summary
    assert alert.possible_cause
    assert alert.recommended_action
    assert alert.acknowledged_at is None
    assert alert.resolved_at is None


async def test_dedup_bumps_occurrence_count_instead_of_new_alert(db, make_monitor):
    monitor = make_monitor()
    first = await _failing_check(db, monitor.id)
    second = await _failing_check(db, monitor.id)
    third = await _failing_check(db, monitor.id)

    assert len(first.alerts_created) == 1
    assert second.alerts_created == []  # deduped
    assert third.alerts_created == []   # deduped again
    alerts = db.query(Alert).all()
    assert len(alerts) == 1
    assert alerts[0].occurrence_count == 3
    assert alerts[0].status == "active"
    # The alert points at the newest anomaly after each bump.
    assert alerts[0].anomaly_id == third.anomalies[0].id


async def test_dedup_still_applies_to_acknowledged_alerts(client, db, make_monitor):
    monitor = make_monitor()
    await _failing_check(db, monitor.id)
    alert = db.query(Alert).first()
    ack = client.patch(f"/api/alerts/{alert.id}/acknowledge")
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    db.expire_all()  # the acknowledge ran in the API's session

    await _failing_check(db, monitor.id)

    assert db.query(Alert).count() == 1  # still deduped while acknowledged
    assert db.query(Alert).first().occurrence_count == 2


async def test_new_alert_created_after_previous_resolved(client, db, make_monitor):
    monitor = make_monitor()
    await _failing_check(db, monitor.id)
    alert = db.query(Alert).first()
    client.patch(f"/api/alerts/{alert.id}/resolve")

    outcome = await _failing_check(db, monitor.id)

    assert len(outcome.alerts_created) == 1
    # The resolve ran in the API's session; expire cached rows first.
    db.expire_all()
    assert db.query(Alert).count() == 2
    statuses = {a.status for a in db.query(Alert).all()}
    assert statuses == {"resolved", "active"}


async def test_different_anomaly_types_create_separate_alerts(db, make_monitor):
    monitor = make_monitor(latency_threshold_ms=100)
    # First a slow check (HIGH_RESPONSE_TIME), then a 500 (HTTP_ERROR).
    slow = mock_client_factory(json_response_handler(delay=0.12))
    await run_check(db, monitor.id, client_factory=slow)
    await _failing_check(db, monitor.id)

    alerts = db.query(Alert).all()
    assert len(alerts) == 2
    assert {a.anomaly_type for a in alerts} == {"HIGH_RESPONSE_TIME", "HTTP_ERROR"}


# --- lifecycle endpoints ----------------------------------------------------

async def test_acknowledge_sets_timestamp_and_is_idempotent(client, db, make_monitor):
    monitor = make_monitor()
    await _failing_check(db, monitor.id)
    alert = db.query(Alert).first()

    response = client.patch(f"/api/alerts/{alert.id}/acknowledge")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_at"] is not None
    assert body["resolved_at"] is None

    # Acknowledging again is a no-op success, not an error.
    again = client.patch(f"/api/alerts/{alert.id}/acknowledge")
    assert again.status_code == 200
    assert again.json()["status"] == "acknowledged"


async def test_resolve_sets_timestamp(client, db, make_monitor):
    monitor = make_monitor()
    await _failing_check(db, monitor.id)
    alert = db.query(Alert).first()

    response = client.patch(f"/api/alerts/{alert.id}/resolve")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None

    # Resolving again is a no-op success.
    again = client.patch(f"/api/alerts/{alert.id}/resolve")
    assert again.status_code == 200
    assert again.json()["status"] == "resolved"


async def test_acknowledge_on_resolved_alert_is_400(client, db, make_monitor):
    monitor = make_monitor()
    await _failing_check(db, monitor.id)
    alert = db.query(Alert).first()
    client.patch(f"/api/alerts/{alert.id}/resolve")

    response = client.patch(f"/api/alerts/{alert.id}/acknowledge")
    assert response.status_code == 400
    assert "resolved" in response.json()["detail"].lower()


def test_alert_lifecycle_404s(client):
    assert client.patch("/api/alerts/999999/acknowledge").status_code == 404
    assert client.patch("/api/alerts/999999/resolve").status_code == 404
    assert client.get("/api/alerts/999999").status_code == 404


# --- detail + list + history ------------------------------------------------

async def test_alert_detail_includes_monitor_anomaly_and_record(
    client, db, make_monitor
):
    monitor = make_monitor(name="Detail API", url="https://example.com/detail")
    await _failing_check(db, monitor.id)
    alert = db.query(Alert).first()

    response = client.get(f"/api/alerts/{alert.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["monitor_name"] == "Detail API"
    assert body["monitor"]["name"] == "Detail API"
    assert body["monitor"]["url"] == "https://example.com/detail"
    assert body["monitor"]["method"] == "GET"
    assert body["anomaly"]["anomaly_type"] == "HTTP_ERROR"
    assert body["record"]["status_code"] == 500
    assert body["record"]["is_success"] is False


async def test_alert_list_filters(client, db, make_monitor):
    m1 = make_monitor(name="M1")
    m2 = make_monitor(name="M2")
    await _failing_check(db, m1.id)  # high severity, active
    await _failing_check(db, m2.id)
    alert2 = db.query(Alert).filter(Alert.monitor_id == m2.id).first()
    client.patch(f"/api/alerts/{alert2.id}/resolve")

    all_alerts = client.get("/api/alerts")
    assert all_alerts.json()["total"] == 2

    active = client.get("/api/alerts", params={"status": "active"})
    assert active.json()["total"] == 1
    assert active.json()["items"][0]["monitor_id"] == m1.id

    resolved = client.get("/api/alerts", params={"status": "resolved"})
    assert resolved.json()["total"] == 1

    by_severity = client.get("/api/alerts", params={"severity": "high"})
    assert by_severity.json()["total"] == 2
    assert client.get("/api/alerts", params={"severity": "critical"}).json()["total"] == 0

    by_monitor = client.get("/api/alerts", params={"monitor_id": m2.id})
    assert by_monitor.json()["total"] == 1

    by_search = client.get("/api/alerts", params={"search": "M1"})
    assert by_search.json()["total"] == 1
    assert by_search.json()["items"][0]["monitor_id"] == m1.id

    assert client.get("/api/alerts", params={"severity": "bogus"}).status_code == 422


async def test_alert_history_returns_only_resolved(client, db, make_monitor):
    m1 = make_monitor(name="M1")
    m2 = make_monitor(name="M2")
    await _failing_check(db, m1.id)
    await _failing_check(db, m2.id)
    alert2 = db.query(Alert).filter(Alert.monitor_id == m2.id).first()
    client.patch(f"/api/alerts/{alert2.id}/resolve")

    history = client.get("/api/alerts/history")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["monitor_id"] == m2.id
    assert history.json()["items"][0]["status"] == "resolved"

    # History accepts the same filters as the main list.
    filtered = client.get("/api/alerts/history", params={"monitor_id": m1.id})
    assert filtered.json()["total"] == 0
