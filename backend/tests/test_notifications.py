"""Telegram notifications: alert + recovery messages, severity gating,
test endpoint, and the guarantee that the bot token never appears in any
API response. No real token is ever used — only obvious fakes.
"""
from __future__ import annotations

import json

import httpx

from app.models.alert import Alert
from app.models.settings import AppSettings
from app.services.monitoring_service import run_check
from app.services.notification_service import (
    TEST_MESSAGE,
    send_test_notification,
)
from app.services.settings_service import get_or_create_settings
from tests.conftest import json_response_handler, mock_client_factory

FAKE_TOKEN = "FAKE_TOKEN"
FAKE_CHAT_ID = "FAKE_CHAT_ID"


def _configure_telegram(db, *, enabled=True, min_severity="high"):
    """Persist Telegram credentials in the settings row."""
    row = get_or_create_settings(db)
    row.telegram_bot_token = FAKE_TOKEN
    row.telegram_chat_id = FAKE_CHAT_ID
    row.telegram_enabled = enabled
    row.telegram_min_severity = min_severity
    db.commit()
    return row


def _telegram_factory(captured: list, *, ok: bool = True, fail: bool = False):
    """A notification client_factory recording every Telegram request."""

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "body": json.loads(request.content.decode()),
            }
        )
        if fail:
            raise httpx.ConnectError("telegram unreachable", request=request)
        return httpx.Response(200, json={"ok": ok, "result": {}})

    return mock_client_factory(handler)


async def _failing_check(db, monitor_id, notify_factory):
    factory = mock_client_factory(json_response_handler(status=500, payload={}))
    return await run_check(
        db,
        monitor_id,
        client_factory=factory,
        notification_client_factory=notify_factory,
    )


async def _healthy_check(db, monitor_id, notify_factory):
    factory = mock_client_factory(json_response_handler(status=200, payload=[{"id": 1}]))
    return await run_check(
        db,
        monitor_id,
        client_factory=factory,
        notification_client_factory=notify_factory,
    )


# --- alert notifications ----------------------------------------------------

async def test_message_sent_on_new_alert(db, make_monitor):
    _configure_telegram(db)
    monitor = make_monitor(alert_after_failures=1)
    captured: list = []

    outcome = await _failing_check(db, monitor.id, _telegram_factory(captured))

    assert len(outcome.alerts_created) == 1
    assert len(captured) == 1
    message = captured[0]
    assert message["url"] == (
        f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
    )
    assert message["body"]["chat_id"] == FAKE_CHAT_ID
    text = message["body"]["text"]
    assert "Example API" in text  # monitor name
    assert "high" in text  # severity
    assert "HTTP_ERROR" in text  # anomaly type
    assert "UTC" in text  # timestamp
    assert "error status" in text.lower()  # a line from the summary


async def test_message_not_sent_when_disabled(db, make_monitor):
    _configure_telegram(db, enabled=False)
    monitor = make_monitor(alert_after_failures=1)
    captured: list = []

    outcome = await _failing_check(db, monitor.id, _telegram_factory(captured))

    assert len(outcome.alerts_created) == 1  # the alert still exists
    assert captured == []


async def test_message_not_sent_below_min_severity(db, make_monitor):
    _configure_telegram(db, min_severity="high")
    monitor = make_monitor(alert_after_failures=1)
    captured: list = []

    # A 404 is an HTTP_ERROR with severity "warning" — below the minimum.
    factory = mock_client_factory(json_response_handler(status=404, payload={}))
    outcome = await run_check(
        db,
        monitor.id,
        client_factory=factory,
        notification_client_factory=_telegram_factory(captured),
    )

    assert len(outcome.alerts_created) == 1
    assert db.query(Alert).first().severity == "warning"
    assert captured == []


async def test_message_sent_when_min_severity_is_warning(db, make_monitor):
    _configure_telegram(db, min_severity="warning")
    monitor = make_monitor(alert_after_failures=1)
    captured: list = []

    factory = mock_client_factory(json_response_handler(status=404, payload={}))
    await run_check(
        db,
        monitor.id,
        client_factory=factory,
        notification_client_factory=_telegram_factory(captured),
    )

    assert len(captured) == 1


async def test_message_not_sent_on_occurrence_bump(db, make_monitor):
    _configure_telegram(db)
    monitor = make_monitor(alert_after_failures=1)
    captured: list = []
    notify_factory = _telegram_factory(captured)

    first = await _failing_check(db, monitor.id, notify_factory)
    second = await _failing_check(db, monitor.id, notify_factory)

    assert len(first.alerts_created) == 1
    assert second.alerts_created == []  # deduped
    assert db.query(Alert).first().occurrence_count == 2
    assert len(captured) == 1  # only the new alert notified


async def test_notification_failure_never_breaks_the_check(db, make_monitor):
    _configure_telegram(db)
    monitor = make_monitor(alert_after_failures=1)
    captured: list = []

    outcome = await _failing_check(
        db, monitor.id, _telegram_factory(captured, fail=True)
    )

    # The check still completed and persisted everything.
    assert outcome.record.is_success is False
    assert outcome.record.status_code == 500
    assert len(outcome.alerts_created) == 1
    assert len(captured) == 1  # the attempt happened; the failure was swallowed


# --- recovery notifications -------------------------------------------------

async def test_recovery_message_sent_when_monitor_comes_back_up(
    db, make_monitor
):
    _configure_telegram(db)
    monitor = make_monitor(alert_after_failures=1)
    monitor.last_status = "down"
    db.add(
        Alert(
            monitor_id=monitor.id,
            anomaly_id=None,
            anomaly_type="HTTP_ERROR",
            title="HTTP error on Example API",
            severity="high",
            summary="s",
            possible_cause="c",
            recommended_action="a",
            status="active",
            ai_generated=False,
            occurrence_count=1,
        )
    )
    db.commit()
    captured: list = []

    outcome = await _healthy_check(db, monitor.id, _telegram_factory(captured))

    assert outcome.record.is_success is True
    assert outcome.alerts_created == []  # no new alert on a healthy check
    assert len(captured) == 1
    text = captured[0]["body"]["text"]
    assert "back up" in text
    assert "Example API" in text
    assert "Response time" in text


async def test_no_recovery_message_without_open_alert(db, make_monitor):
    _configure_telegram(db)
    monitor = make_monitor(alert_after_failures=1)
    monitor.last_status = "down"  # was down, but no open alert exists
    db.commit()
    captured: list = []

    await _healthy_check(db, monitor.id, _telegram_factory(captured))

    assert captured == []


async def test_no_recovery_message_when_monitor_was_up(db, make_monitor):
    _configure_telegram(db)
    monitor = make_monitor(alert_after_failures=1)
    monitor.last_status = "up"
    db.add(
        Alert(
            monitor_id=monitor.id,
            anomaly_id=None,
            anomaly_type="HTTP_ERROR",
            title="t",
            severity="high",
            summary="s",
            possible_cause="c",
            recommended_action="a",
            status="active",
            ai_generated=False,
            occurrence_count=1,
        )
    )
    db.commit()
    captured: list = []

    await _healthy_check(db, monitor.id, _telegram_factory(captured))

    # The monitor was never down, so there is nothing to recover from.
    assert captured == []


# --- test endpoint ----------------------------------------------------------

def test_test_notification_without_config_returns_success_false(client):
    response = client.post("/api/settings/test-notification")
    assert response.status_code == 200  # not a 500
    body = response.json()
    assert body["success"] is False
    assert body["detail"] == "Telegram not configured"


async def test_send_test_notification_sends_test_message(db):
    _configure_telegram(db, enabled=False)  # test ignores the enabled toggle
    captured: list = []

    success, detail = await send_test_notification(
        db, client_factory=_telegram_factory(captured)
    )

    assert success is True
    assert detail == "Test notification sent"
    assert len(captured) == 1
    assert captured[0]["body"]["text"] == TEST_MESSAGE


async def test_send_test_notification_reports_delivery_failure(db):
    _configure_telegram(db)
    captured: list = []

    success, detail = await send_test_notification(
        db, client_factory=_telegram_factory(captured, ok=False)
    )

    assert success is False
    assert "Failed to send" in detail


def test_test_notification_route_returns_service_result(client, db, monkeypatch):
    """The route forwards the service result (the real send is covered by
    the service-level tests above)."""
    import app.api.routes.settings as settings_route

    async def _fake_send(db_session, client_factory=None):  # noqa: ARG001
        return True, "Test notification sent"

    monkeypatch.setattr(settings_route, "send_test_notification", _fake_send)
    response = client.post("/api/settings/test-notification")
    assert response.status_code == 200
    assert response.json() == {"success": True, "detail": "Test notification sent"}


# --- settings API: token handling -------------------------------------------

def test_settings_defaults_include_telegram_fields(client):
    body = client.get("/api/settings").json()
    assert body["telegram_enabled"] is False
    assert body["telegram_min_severity"] == "high"
    assert body["telegram_configured"] is False
    assert body["retention_days"] == 90
    assert body["alert_retention_days"] == 365


def test_token_never_appears_in_any_settings_response(client, db):
    put = client.put(
        "/api/settings",
        json={
            "telegram_bot_token": FAKE_TOKEN,
            "telegram_chat_id": FAKE_CHAT_ID,
            "telegram_enabled": True,
        },
    )
    assert put.status_code == 200
    assert FAKE_TOKEN not in put.text
    assert put.json()["telegram_configured"] is True

    get = client.get("/api/settings")
    assert FAKE_TOKEN not in get.text
    assert get.json()["telegram_configured"] is True

    preview = client.get("/api/settings/cleanup-preview")
    assert FAKE_TOKEN not in preview.text


def test_chat_id_returned_and_survives_resave(client, db):
    """Regression test: GET /api/settings must return telegram_chat_id.

    Without it the Settings form reloads with an empty chat-id field, and
    the next save would overwrite the stored chat id with "".
    """
    put = client.put(
        "/api/settings",
        json={
            "telegram_bot_token": FAKE_TOKEN,
            "telegram_chat_id": FAKE_CHAT_ID,
            "telegram_enabled": True,
        },
    )
    assert put.status_code == 200
    assert put.json()["telegram_chat_id"] == FAKE_CHAT_ID

    get = client.get("/api/settings")
    assert get.json()["telegram_chat_id"] == FAKE_CHAT_ID

    # Re-saving with the value the UI now holds must not wipe it.
    resave = client.put("/api/settings", json={"telegram_chat_id": FAKE_CHAT_ID})
    assert resave.status_code == 200
    assert resave.json()["telegram_chat_id"] == FAKE_CHAT_ID
    assert resave.json()["telegram_configured"] is True


def test_masked_token_keeps_stored_value(client, db):
    client.put(
        "/api/settings",
        json={"telegram_bot_token": FAKE_TOKEN, "telegram_chat_id": FAKE_CHAT_ID},
    )
    response = client.put("/api/settings", json={"telegram_bot_token": "********"})
    assert response.status_code == 200
    assert response.json()["telegram_configured"] is True

    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    assert row.telegram_bot_token == FAKE_TOKEN  # unchanged


def test_null_token_clears_stored_value(client, db):
    client.put(
        "/api/settings",
        json={"telegram_bot_token": FAKE_TOKEN, "telegram_chat_id": FAKE_CHAT_ID},
    )
    assert client.get("/api/settings").json()["telegram_configured"] is True

    client.put("/api/settings", json={"telegram_bot_token": None})
    assert client.get("/api/settings").json()["telegram_configured"] is False
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    assert row.telegram_bot_token is None


def test_telegram_settings_validation(client):
    assert client.put(
        "/api/settings", json={"telegram_min_severity": "bogus"}
    ).status_code == 422
    assert client.put(
        "/api/settings", json={"telegram_min_severity": "critical"}
    ).status_code == 200
    assert client.put("/api/settings", json={"retention_days": 6}).status_code == 422
    assert client.put("/api/settings", json={"retention_days": 366}).status_code == 422
    assert client.put(
        "/api/settings", json={"alert_retention_days": 29}
    ).status_code == 422
    assert client.put(
        "/api/settings", json={"alert_retention_days": 1096}
    ).status_code == 422
    ok = client.put(
        "/api/settings", json={"retention_days": 7, "alert_retention_days": 30}
    )
    assert ok.status_code == 200
    assert ok.json()["retention_days"] == 7
    assert ok.json()["alert_retention_days"] == 30
