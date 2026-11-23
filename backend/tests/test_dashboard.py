"""Dashboard: summary, performance, and health aggregations.

Records and alerts are seeded directly in the DB, then the endpoints must
return the exact numbers those rows imply — no hardcoded or fake data.
"""
from __future__ import annotations

from datetime import timedelta

from app.models.alert import Alert
from app.models.monitoring_record import MonitoringRecord
from app.utils.time import utcnow


def _seed_record(db, monitor_id, *, rt_ms, success, hours_ago=0.0, minutes_ago=0.0):
    db.add(
        MonitoringRecord(
            monitor_id=monitor_id,
            response_time_ms=rt_ms,
            status_code=200 if success else 500,
            response_size_bytes=100,
            records_returned=1,
            is_success=success,
            checked_at=utcnow() - timedelta(hours=hours_ago, minutes=minutes_ago),
        )
    )


def _seed_alert(db, monitor_id, *, severity="high", status="active"):
    db.add(
        Alert(
            monitor_id=monitor_id,
            anomaly_id=None,
            anomaly_type="HTTP_ERROR",
            title=f"Alert on {monitor_id}",
            severity=severity,
            summary="s",
            possible_cause="c",
            recommended_action="a",
            status=status,
            ai_generated=False,
            occurrence_count=1,
        )
    )


def _seed_scenario(db, make_monitor):
    """3 monitors + 5 recent checks (1 failed) + 1 stale check + 3 alerts."""
    m_up = make_monitor(name="Up API")
    m_down = make_monitor(name="Down API")
    m_unknown = make_monitor(name="Never checked", is_active=False)
    m_up.last_status = "up"
    m_down.last_status = "down"
    db.commit()

    # 4 successful + 1 failed check in the last 24h.
    _seed_record(db, m_up.id, rt_ms=100.0, success=True, minutes_ago=10)
    _seed_record(db, m_up.id, rt_ms=200.0, success=True, minutes_ago=20)
    _seed_record(db, m_up.id, rt_ms=300.0, success=True, minutes_ago=30)
    _seed_record(db, m_down.id, rt_ms=400.0, success=True, minutes_ago=40)
    _seed_record(db, m_down.id, rt_ms=500.0, success=False, minutes_ago=50)
    # One stale check (25h ago): excluded from every 24h aggregation.
    _seed_record(db, m_up.id, rt_ms=9999.0, success=False, hours_ago=25)

    _seed_alert(db, m_down.id, severity="critical", status="active")
    _seed_alert(db, m_down.id, severity="warning", status="active")
    _seed_alert(db, m_up.id, severity="critical", status="resolved")
    db.commit()
    return m_up, m_down, m_unknown


def test_summary_aggregates_seeded_data(client, db, make_monitor):
    _seed_scenario(db, make_monitor)

    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()

    assert body["total_monitors"] == 3
    assert body["active_monitors"] == 2
    assert body["healthy_monitors"] == 1
    assert body["unhealthy_monitors"] == 1
    assert body["unknown_monitors"] == 1
    assert body["active_alerts"] == 2  # resolved alert does not count
    assert body["critical_alerts"] == 1  # only the ACTIVE critical one
    assert body["total_checks_24h"] == 5  # stale check excluded
    assert body["failed_checks_24h"] == 1
    assert body["overall_uptime_pct"] == 80.0  # 4 of 5 succeeded
    # Avg includes the failed check's timing: (100+200+300+400+500)/5 = 300.
    assert body["avg_response_time_ms"] == 300.0


def test_summary_with_empty_database(client):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_monitors"] == 0
    assert body["total_checks_24h"] == 0
    assert body["overall_uptime_pct"] == 100.0  # no checks -> 100% by definition
    assert body["avg_response_time_ms"] == 0.0


def test_performance_returns_points_in_time_order(client, db, make_monitor):
    m_up, m_down, _ = _seed_scenario(db, make_monitor)

    response = client.get("/api/dashboard/performance")
    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 5  # stale check excluded
    times = [p["time"] for p in points]
    assert times == sorted(times)  # ascending by time
    assert {p["monitor_name"] for p in points} == {"Up API", "Down API"}
    assert all("response_time_ms" in p and "is_success" in p for p in points)
    assert sum(1 for p in points if not p["is_success"]) == 1

    # Filter to one monitor.
    only_up = client.get(
        "/api/dashboard/performance", params={"monitor_id": m_up.id}
    ).json()["points"]
    assert len(only_up) == 3
    assert all(p["monitor_id"] == m_up.id for p in only_up)

    # A 1-hour window still covers all 5 (they are <= 50 minutes old).
    one_hour = client.get(
        "/api/dashboard/performance", params={"hours": 1}
    ).json()["points"]
    assert len(one_hour) == 5

    assert client.get("/api/dashboard/performance", params={"hours": 0}).status_code == 422
    assert client.get("/api/dashboard/performance", params={"hours": 169}).status_code == 422


def test_performance_buckets_to_at_most_200_points(client, db, make_monitor):
    monitor = make_monitor()
    for i in range(250):
        _seed_record(db, monitor.id, rt_ms=100.0, success=True, minutes_ago=i)
    db.commit()

    points = client.get("/api/dashboard/performance").json()["points"]
    assert len(points) == 200


def test_health_returns_per_monitor_uptime_and_alerts(client, db, make_monitor):
    m_up, m_down, m_unknown = _seed_scenario(db, make_monitor)

    response = client.get("/api/dashboard/health")
    assert response.status_code == 200
    items = {m["monitor_id"]: m for m in response.json()["monitors"]}
    assert len(items) == 3

    up = items[m_up.id]
    assert up["status"] == "up"
    assert up["uptime_pct"] == 100.0  # 3/3 recent checks succeeded
    assert up["avg_response_time_ms"] == 200.0  # (100+200+300)/3
    assert up["active_alerts"] == 0  # its only alert is resolved

    down = items[m_down.id]
    assert down["status"] == "down"
    assert down["uptime_pct"] == 50.0  # 1/2 recent checks succeeded
    assert down["avg_response_time_ms"] == 450.0  # (400+500)/2
    assert down["active_alerts"] == 2

    unknown = items[m_unknown.id]
    assert unknown["status"] == "unknown"
    assert unknown["uptime_pct"] == 100.0  # no checks -> 100% by definition
    assert unknown["avg_response_time_ms"] == 0.0
    assert unknown["active_alerts"] == 0
