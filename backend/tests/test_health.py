"""Health + root endpoints."""
from __future__ import annotations


def test_root_returns_project_info(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "project": "PulseWatch AI",
        "version": "1.0.0",
    }


def test_health_reports_db_ok_and_scheduler_disabled_under_pytest(client):
    # PULSEWATCH_TESTING=1 (set in conftest) keeps the scheduler off.
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["scheduler"] == "disabled"


def test_health_answers_head_for_uptime_checkers(client):
    # UptimeRobot's free plan probes with HEAD; a GET-only route 405s.
    response = client.head("/health")
    assert response.status_code == 200
    assert response.content == b""


def test_unknown_route_is_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
