"""Manual checks (mocked HTTP transport) + history endpoints.

Every check scenario runs through the real ``run_check`` pipeline — HTTP
fetch, record persistence, the 10 anomaly rules, monitor snapshot update,
and alert creation — with only the network mocked via ``client_factory``.
DNS is mocked to a public IP by the conftest fixture.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.core.config import settings
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.services.monitoring_service import run_check
from app.utils.time import utcnow
from tests.conftest import (
    TEST_URL,
    json_response_handler,
    mock_client_factory,
)


def _anomaly_types(db, monitor_id: int) -> set[str]:
    rows = db.query(Anomaly).filter(Anomaly.monitor_id == monitor_id).all()
    return {row.anomaly_type for row in rows}


# --- healthy / slow ---------------------------------------------------------

async def test_healthy_200_json_check_counts_records(db, make_monitor):
    monitor = make_monitor(expected_fields=["id", "title"], check_zero_records=True)
    payload = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}, {"id": 3, "title": "c"}]
    factory = mock_client_factory(json_response_handler(status=200, payload=payload))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    record = outcome.record
    assert record.is_success is True
    assert record.status_code == 200
    assert record.records_returned == 3
    assert record.is_valid_json is True
    assert record.response_time_ms is not None and record.response_time_ms > 0
    assert record.response_size_bytes > 0
    assert outcome.anomalies == []
    assert outcome.alerts_created == []

    db.refresh(monitor)
    assert monitor.last_status == "up"
    assert monitor.last_status_code == 200
    assert monitor.last_checked_at is not None
    assert db.query(Alert).count() == 0


async def test_slow_response_triggers_high_response_time_warning(db, make_monitor):
    # 120ms delay vs a 100ms threshold -> ~1.2x -> warning tier.
    monitor = make_monitor(latency_threshold_ms=100)
    factory = mock_client_factory(json_response_handler(delay=0.12))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is True  # slow, but still a success
    assert _anomaly_types(db, monitor.id) == {"HIGH_RESPONSE_TIME"}
    anomaly = outcome.anomalies[0]
    assert anomaly.severity == "warning"
    assert db.query(Alert).count() == 1
    alert = db.query(Alert).first()
    assert alert.anomaly_type == "HIGH_RESPONSE_TIME"
    assert alert.severity == "warning"
    assert alert.ai_generated is False  # no Gemini key in tests


async def test_very_slow_response_is_critical(db, make_monitor):
    # 500ms delay vs a 100ms threshold -> ~5x -> critical tier.
    monitor = make_monitor(latency_threshold_ms=100)
    factory = mock_client_factory(json_response_handler(delay=0.5))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.anomalies[0].severity == "critical"
    assert db.query(Alert).first().severity == "critical"


async def test_object_body_counts_records_from_data_key(db, make_monitor):
    monitor = make_monitor(check_zero_records=True)
    payload = {"data": [{"id": 1}, {"id": 2}], "total": 2}
    factory = mock_client_factory(json_response_handler(payload=payload))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.records_returned == 2
    assert outcome.anomalies == []


# --- error scenarios --------------------------------------------------------

async def test_500_response_is_http_error_and_marks_monitor_down(db, make_monitor):
    # alert_after_failures=1: this test asserts an alert on the first failure.
    monitor = make_monitor(alert_after_failures=1)
    factory = mock_client_factory(json_response_handler(status=500, payload={}))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is False
    assert outcome.record.status_code == 500
    assert _anomaly_types(db, monitor.id) == {"HTTP_ERROR"}
    assert outcome.anomalies[0].severity == "high"
    assert len(outcome.alerts_created) == 1

    db.refresh(monitor)
    assert monitor.last_status == "down"
    assert monitor.last_status_code == 500


async def test_404_response_is_http_error_warning(db, make_monitor):
    monitor = make_monitor()
    factory = mock_client_factory(json_response_handler(status=404, payload={}))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is False
    assert outcome.anomalies[0].anomaly_type == "HTTP_ERROR"
    assert outcome.anomalies[0].severity == "warning"


async def test_timeout_produces_timeout_anomaly(db, make_monitor):
    monitor = make_monitor(timeout_seconds=5)

    async def handler(request: httpx.Request):
        raise httpx.ReadTimeout("read timed out", request=request)

    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert outcome.record.is_success is False
    assert outcome.record.status_code is None
    assert outcome.record.error_message is not None
    assert "timed out" in outcome.record.error_message.lower()
    assert _anomaly_types(db, monitor.id) == {"TIMEOUT"}
    db.refresh(monitor)
    assert monitor.last_status == "down"


async def test_invalid_json_produces_invalid_response(db, make_monitor):
    monitor = make_monitor(expected_fields=["id"])  # JSON is expected

    async def handler(request: httpx.Request):  # noqa: ARG001
        return httpx.Response(
            200,
            content=b"<html>not json at all</html>",
            headers={"content-type": "text/html"},
        )

    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert outcome.record.is_success is False
    assert outcome.record.is_valid_json is False
    assert outcome.record.records_returned is None
    assert _anomaly_types(db, monitor.id) == {"INVALID_RESPONSE"}
    assert outcome.anomalies[0].severity == "high"


async def test_zero_records_when_enabled(db, make_monitor):
    monitor = make_monitor(check_zero_records=True)
    factory = mock_client_factory(json_response_handler(payload=[]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.records_returned == 0
    assert outcome.record.is_success is True  # 200 + valid JSON still succeeds
    assert _anomaly_types(db, monitor.id) == {"ZERO_RECORDS"}


async def test_zero_records_ignored_when_disabled(db, make_monitor):
    monitor = make_monitor(check_zero_records=False)
    factory = mock_client_factory(json_response_handler(payload=[]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.records_returned == 0
    assert outcome.anomalies == []


async def test_missing_expected_field(db, make_monitor):
    monitor = make_monitor(expected_fields=["id", "title", "email"])
    payload = [{"id": 1, "title": "x"}]  # no "email"
    factory = mock_client_factory(json_response_handler(payload=payload))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert _anomaly_types(db, monitor.id) == {"MISSING_FIELDS"}
    assert "email" in outcome.anomalies[0].description


async def test_unexpected_status_201_when_200_expected(db, make_monitor):
    monitor = make_monitor(expected_status_codes=[200])
    factory = mock_client_factory(json_response_handler(status=201, payload={}))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is False
    assert _anomaly_types(db, monitor.id) == {"UNEXPECTED_STATUS"}
    # 201 is not an HTTP_ERROR (that rule is for 4xx/5xx).
    assert "HTTP_ERROR" not in _anomaly_types(db, monitor.id)


async def test_oversized_response_triggers_large_response(db, make_monitor):
    monitor = make_monitor(max_response_size_bytes=100)
    payload = {"pad": "x" * 500}  # ~520 bytes, 5x the limit
    factory = mock_client_factory(json_response_handler(payload=payload))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.response_size_bytes > 100
    assert _anomaly_types(db, monitor.id) == {"LARGE_RESPONSE"}
    assert outcome.anomalies[0].severity == "high"  # >= 5x


async def test_historical_anomaly_from_seeded_history(db, make_monitor):
    monitor = make_monitor(latency_threshold_ms=3000)  # no HIGH_RESPONSE_TIME
    # Seed 12 prior checks at ~100ms so the historical rule has a baseline.
    base = utcnow() - timedelta(minutes=30)
    for i in range(12):
        db.add(
            MonitoringRecord(
                monitor_id=monitor.id,
                response_time_ms=95.0 + i,
                status_code=200,
                response_size_bytes=100,
                records_returned=1,
                is_success=True,
                checked_at=base + timedelta(minutes=i),
            )
        )
    db.commit()

    # A 500ms check is ~5x the ~100ms baseline -> HISTORICAL_ANOMALY.
    factory = mock_client_factory(json_response_handler(delay=0.5))
    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert "HISTORICAL_ANOMALY" in _anomaly_types(db, monitor.id)
    assert "HIGH_RESPONSE_TIME" not in _anomaly_types(db, monitor.id)


async def test_post_check_sends_request_body(db, make_monitor):
    monitor = make_monitor(method="POST", request_body='{"name": "test"}')
    seen: dict = {}

    async def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"id": 1})

    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert outcome.record.is_success is True
    assert seen["method"] == "POST"
    assert json.loads(seen["body"]) == {"name": "test"}


async def test_connect_error_marks_check_failed_without_status(db, make_monitor):
    # alert_after_failures=1: this test asserts an alert on the first failure.
    monitor = make_monitor(alert_after_failures=1)

    async def handler(request: httpx.Request):
        raise httpx.ConnectError("connection refused", request=request)

    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert outcome.record.is_success is False
    assert outcome.record.status_code is None
    assert outcome.record.error_message == "Connection failed (DNS/network)"
    db.refresh(monitor)
    assert monitor.last_status == "down"
    # A connect failure is a real incident: NETWORK_ERROR anomaly + alert.
    assert _anomaly_types(db, monitor.id) == {"NETWORK_ERROR"}
    assert outcome.anomalies[0].severity == "high"
    assert len(outcome.alerts_created) == 1
    alert = db.query(Alert).first()
    assert alert.anomaly_type == "NETWORK_ERROR"
    assert alert.ai_generated is False  # no Gemini key in tests


async def test_ssrf_blocked_check_records_failure(db, make_monitor):
    # Loopback URL with ALLOW_LOCAL_URLS=false: blocked before any request.
    monitor = make_monitor(url="http://127.0.0.1:9/unreachable")
    calls = {"n": 0}

    async def handler(request: httpx.Request):  # noqa: ARG001
        calls["n"] += 1
        return httpx.Response(200, json={})

    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert calls["n"] == 0  # the transport was never reached
    assert outcome.record.is_success is False
    assert outcome.record.status_code is None
    assert "non-public" in (outcome.record.error_message or "")
    db.refresh(monitor)
    assert monitor.last_status == "down"
    # SSRF blocks are policy outcomes, not API failures: no anomaly/alert.
    assert outcome.anomalies == []
    assert outcome.alerts_created == []
    assert db.query(Alert).count() == 0


async def test_check_for_missing_monitor_raises(db):
    from app.services.monitoring_service import MonitorNotFoundError

    with pytest.raises(MonitorNotFoundError):
        await run_check(db, 999999)


# --- redirect handling ------------------------------------------------------

async def test_redirect_followed_to_final_url(db, make_monitor):
    async def handler(request: httpx.Request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, json=[{"id": 1}])

    monitor = make_monitor(url="https://example.com/start")
    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert outcome.record.is_success is True
    assert outcome.record.status_code == 200


async def test_redirect_to_private_ip_is_blocked(db, make_monitor):
    async def handler(request: httpx.Request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:9/evil"})

    monitor = make_monitor(url="https://example.com/start")
    outcome = await run_check(db, monitor.id, client_factory=mock_client_factory(handler))

    assert outcome.record.is_success is False
    assert outcome.record.status_code is None
    assert "non-public" in (outcome.record.error_message or "")


# --- POST /api/monitors/{id}/check (route level) ----------------------------

async def test_api_check_endpoint_runs_real_pipeline(client, db, make_monitor, monkeypatch):
    """The route calls run_check; inject the mocked transport through it."""
    import app.api.routes.monitors as monitors_route
    from app.services import monitoring_service

    # alert_after_failures=1: this test asserts an alert on the first failure.
    monitor = make_monitor(alert_after_failures=1)
    factory = mock_client_factory(json_response_handler(status=500, payload={}))

    async def run_check_with_mock(db_session, monitor_id, **kwargs):  # noqa: ARG001
        return await monitoring_service.run_check(
            db_session, monitor_id, client_factory=factory
        )

    monkeypatch.setattr(monitors_route, "run_check", run_check_with_mock)

    response = client.post(f"/api/monitors/{monitor.id}/check")
    assert response.status_code == 200
    body = response.json()
    assert body["monitor_id"] == monitor.id
    assert body["is_success"] is False
    assert body["status_code"] == 500
    assert body["anomalies"][0]["anomaly_type"] == "HTTP_ERROR"
    assert len(body["alerts_created"]) == 1

    assert client.post("/api/monitors/999999/check").status_code == 404


# --- history endpoints ------------------------------------------------------

def _seed_records(db, monitor_id: int, count: int, *, success: bool = True):
    base = utcnow()
    for i in range(count):
        db.add(
            MonitoringRecord(
                monitor_id=monitor_id,
                response_time_ms=100.0 + i,
                status_code=200 if success else 500,
                response_size_bytes=100,
                records_returned=1,
                is_success=success,
                checked_at=base - timedelta(minutes=i),
            )
        )
    db.commit()


def test_history_list_filters_and_pagination(client, db, make_monitor):
    m1 = make_monitor(name="M1")
    m2 = make_monitor(name="M2")
    _seed_records(db, m1.id, 3, success=True)
    _seed_records(db, m1.id, 2, success=False)
    _seed_records(db, m2.id, 1, success=True)

    all_history = client.get("/api/monitoring/history")
    assert all_history.json()["total"] == 6

    only_m1 = client.get("/api/monitoring/history", params={"monitor_id": m1.id})
    assert only_m1.json()["total"] == 5

    only_failed = client.get("/api/monitoring/history", params={"is_success": False})
    assert only_failed.json()["total"] == 2

    combined = client.get(
        "/api/monitoring/history",
        params={"monitor_id": m1.id, "is_success": True},
    )
    assert combined.json()["total"] == 3

    page = client.get("/api/monitoring/history", params={"page": 2, "page_size": 5})
    assert page.json()["total"] == 6
    assert len(page.json()["items"]) == 1

    # History items are the light shape: no embedded anomalies.
    assert "anomalies" not in all_history.json()["items"][0]


def test_history_time_range_filter(client, db, make_monitor):
    monitor = make_monitor()
    _seed_records(db, monitor.id, 3)  # all within the last ~3 minutes
    old = MonitoringRecord(
        monitor_id=monitor.id,
        response_time_ms=100.0,
        status_code=200,
        response_size_bytes=100,
        records_returned=1,
        is_success=True,
        checked_at=utcnow() - timedelta(days=3),
    )
    db.add(old)
    db.commit()

    recent = client.get(
        "/api/monitoring/history",
        params={"from": (utcnow() - timedelta(hours=1)).isoformat()},
    )
    assert recent.json()["total"] == 3

    ancient = client.get(
        "/api/monitoring/history",
        params={"to": (utcnow() - timedelta(days=1)).isoformat()},
    )
    assert ancient.json()["total"] == 1


def test_history_for_one_monitor_and_404(client, db, make_monitor):
    m1 = make_monitor(name="M1")
    m2 = make_monitor(name="M2")
    _seed_records(db, m1.id, 2)
    _seed_records(db, m2.id, 4)

    scoped = client.get(f"/api/monitoring/history/{m1.id}")
    assert scoped.json()["total"] == 2

    missing = client.get("/api/monitoring/history/999999")
    assert missing.status_code == 404


# --- live check against a real local server ---------------------------------

class _JsonHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps([{"id": 1, "title": "live"}]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the server during tests
        pass


async def test_live_check_against_local_server_with_allow_local(
    db, make_monitor, monkeypatch
):
    """One real end-to-end check (real socket, real httpx client) against a
    local server — the only live network test; it needs ALLOW_LOCAL_URLS."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JsonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monitor = make_monitor(
            url=f"http://127.0.0.1:{port}/posts",
            expected_fields=["id", "title"],
            check_zero_records=True,
        )
        monkeypatch.setattr(settings, "ALLOW_LOCAL_URLS", True)
        # Go direct: never route a loopback check through a proxy.
        for var in (
            "HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
            "https_proxy", "ALL_PROXY", "all_proxy",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("NO_PROXY", "*")

        outcome = await run_check(db, monitor.id)  # no client_factory: real HTTP

        assert outcome.record.is_success is True
        assert outcome.record.status_code == 200
        assert outcome.record.records_returned == 1
        assert outcome.anomalies == []
    finally:
        server.shutdown()
        server.server_close()
