"""SSL expiry monitoring: the 11th anomaly rule, the cert refresh
(https-only, 24h cache, never fails a check), and the response fields.
The real socket fetch is always mocked — no live cert lookups in tests.
"""
from __future__ import annotations

from datetime import timedelta

from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.services import monitoring_service
from app.services.anomaly_service import (
    AnomalyContext,
    check_ssl_expiring,
    detect_anomalies,
)
from app.services.monitoring_service import run_check
from app.utils.time import utcnow
from tests.conftest import json_response_handler, mock_client_factory


def _expiry_in(days: float):
    """A naive-UTC expiry N days from now (matching stored values)."""
    return (utcnow() + timedelta(days=days)).replace(tzinfo=None)


def _mock_cert_fetch(monkeypatch, *, expiry=None, calls: list | None = None):
    """Patch the cert fetch used by run_check with a canned expiry."""

    def _fake(hostname, port=443, timeout=10):  # noqa: ARG001
        if calls is not None:
            calls.append((hostname, port))
        return expiry

    monkeypatch.setattr(monitoring_service, "fetch_cert_expiry", _fake)


# --- the rule itself ---------------------------------------------------------

def test_ssl_rule_no_expiry_is_no_finding():
    assert check_ssl_expiring(None, utcnow()) is None


def test_ssl_rule_31_days_is_no_finding():
    assert check_ssl_expiring(_expiry_in(31), utcnow()) is None


def test_ssl_rule_20_days_is_warning():
    finding = check_ssl_expiring(_expiry_in(20), utcnow())
    assert finding is not None
    assert finding.anomaly_type == "SSL_EXPIRING"
    assert finding.severity == "warning"


def test_ssl_rule_30_day_boundary_is_warning():
    assert check_ssl_expiring(_expiry_in(30), utcnow()).severity == "warning"


def test_ssl_rule_5_days_is_high():
    finding = check_ssl_expiring(_expiry_in(5), utcnow())
    assert finding.anomaly_type == "SSL_EXPIRING"
    assert finding.severity == "high"


def test_ssl_rule_7_day_boundary_is_high():
    assert check_ssl_expiring(_expiry_in(7), utcnow()).severity == "high"


def test_ssl_rule_expired_is_critical():
    finding = check_ssl_expiring(_expiry_in(-1), utcnow())
    assert finding.anomaly_type == "SSL_EXPIRING"
    assert finding.severity == "critical"
    assert "expired" in finding.description


def test_ssl_rule_wired_into_detect_anomalies():
    findings = detect_anomalies(
        AnomalyContext(
            response_time_ms=100.0,
            status_code=200,
            cert_expires_at=_expiry_in(5),
            now=utcnow(),
        )
    )
    assert [f.anomaly_type for f in findings] == ["SSL_EXPIRING"]
    assert findings[0].severity == "high"


# --- run_check integration --------------------------------------------------

async def test_expiring_cert_creates_anomaly_and_alert(
    db, make_monitor, monkeypatch
):
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(5))
    monitor = make_monitor(alert_after_failures=1)
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is True  # the API is up; only the cert warns
    assert [a.anomaly_type for a in outcome.anomalies] == ["SSL_EXPIRING"]
    assert outcome.anomalies[0].severity == "high"
    assert len(outcome.alerts_created) == 1
    alert = db.query(Alert).first()
    assert alert.anomaly_type == "SSL_EXPIRING"
    assert alert.severity == "high"

    db.refresh(monitor)
    assert monitor.cert_expires_at is not None
    assert monitor.cert_checked_at is not None


async def test_healthy_cert_produces_no_ssl_anomaly(db, make_monitor, monkeypatch):
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(90))
    monitor = make_monitor()
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.anomalies == []
    assert outcome.alerts_created == []
    db.refresh(monitor)
    assert monitor.cert_expires_at is not None  # the expiry was still stored


async def test_http_url_skips_cert_fetch(db, make_monitor, monkeypatch):
    calls: list = []
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(5), calls=calls)
    monitor = make_monitor(url="http://example.com/api")
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert calls == []  # never fetched for an http URL
    assert outcome.anomalies == []
    db.refresh(monitor)
    assert monitor.cert_expires_at is None
    assert monitor.cert_checked_at is None


async def test_cert_fetch_failure_does_not_fail_the_check(
    db, make_monitor, monkeypatch
):
    _mock_cert_fetch(monkeypatch, expiry=None)  # fetch failed -> unknown
    monitor = make_monitor()
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert outcome.record.is_success is True
    assert outcome.anomalies == []
    db.refresh(monitor)
    assert monitor.cert_expires_at is None
    assert monitor.cert_checked_at is None  # not marked checked on failure


async def test_cert_fetch_uses_sni_hostname_and_port(db, make_monitor, monkeypatch):
    calls: list = []
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(90), calls=calls)
    monitor = make_monitor(url="https://example.com:8443/api")
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    await run_check(db, monitor.id, client_factory=factory)

    assert calls == [("example.com", 8443)]


async def test_cert_refresh_cached_for_24h(db, make_monitor, monkeypatch):
    calls: list = []
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(90), calls=calls)
    monitor = make_monitor()
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    await run_check(db, monitor.id, client_factory=factory)
    assert len(calls) == 1

    # Second check within 24h: no re-fetch.
    await run_check(db, monitor.id, client_factory=factory)
    assert len(calls) == 1

    # After 25h the cache is stale: the next check re-fetches.
    db.refresh(monitor)
    monitor.cert_checked_at = utcnow() - timedelta(hours=25)
    db.commit()
    await run_check(db, monitor.id, client_factory=factory)
    assert len(calls) == 2


async def test_expired_stored_cert_is_critical_without_refetch(
    db, make_monitor, monkeypatch
):
    """The stored expiry keeps aging: even though the handshake for an
    expired cert fails (fetch returns None), the rule fires critical on
    the last-known expiry."""
    calls: list = []
    _mock_cert_fetch(monkeypatch, expiry=None, calls=calls)
    monitor = make_monitor(alert_after_failures=1)
    monitor.cert_expires_at = _expiry_in(-2)  # expired 2 days ago
    monitor.cert_checked_at = utcnow()  # fresh check: no re-fetch needed
    db.commit()
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    outcome = await run_check(db, monitor.id, client_factory=factory)

    assert calls == []  # cache was fresh
    assert [a.anomaly_type for a in outcome.anomalies] == ["SSL_EXPIRING"]
    assert outcome.anomalies[0].severity == "critical"


async def test_ssl_anomaly_dedupes_like_other_types(db, make_monitor, monkeypatch):
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(5))
    monitor = make_monitor(alert_after_failures=1)
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))

    first = await run_check(db, monitor.id, client_factory=factory)
    second = await run_check(db, monitor.id, client_factory=factory)

    assert len(first.alerts_created) == 1
    assert second.alerts_created == []  # deduped
    assert db.query(Alert).count() == 1
    assert db.query(Alert).first().occurrence_count == 2
    assert db.query(Anomaly).count() == 2  # one anomaly per check


# --- response fields ---------------------------------------------------------

async def test_monitor_response_includes_cert_fields(
    client, db, make_monitor, monkeypatch
):
    _mock_cert_fetch(monkeypatch, expiry=_expiry_in(10))
    monitor = make_monitor()
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))
    await run_check(db, monitor.id, client_factory=factory)

    body = client.get(f"/api/monitors/{monitor.id}").json()
    assert body["cert_expires_at"] is not None
    # Pydantic serializes the UTC offset as "Z".
    assert body["cert_expires_at"].endswith(("Z", "+00:00"))
    assert body["cert_days_remaining"] == 10.0
