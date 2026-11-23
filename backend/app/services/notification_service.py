"""Telegram notifications for new alerts and recoveries.

- Config: DB (AppSettings) wins, env vars (TELEGRAM_BOT_TOKEN /
  TELEGRAM_CHAT_ID) are the fallback. The token is never logged and never
  returned by any API response.
- Only NEW alerts notify, and only when enabled and the alert severity is
  at or above the configured minimum. Dedup bumps never notify.
- Recovery notifies when a check succeeds after the monitor was down and
  an open alert exists for it.
- Sending never raises: any failure logs a warning and returns False, so
  monitoring is never broken by a notification problem. The httpx client
  is injectable via ``client_factory`` for tests (same pattern as
  ai_service).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.alert import Alert
from app.models.monitor import Monitor
from app.models.settings import AppSettings
from app.services.http_client import build_async_client
from app.utils.time import to_naive_utc

logger = get_logger("notifications")

TELEGRAM_API_BASE = "https://api.telegram.org"
NOTIFY_TIMEOUT_SECONDS = 10.0
SEVERITY_ORDER = {"info": 0, "warning": 1, "high": 2, "critical": 3}
TEST_MESSAGE = (
    "PulseWatch test notification — if you received this, "
    "Telegram alerts are working."
)


@dataclass
class TelegramConfig:
    token: str
    chat_id: str
    enabled: bool
    min_severity: str


def resolve_telegram_credentials(
    row: AppSettings | None,
) -> tuple[str | None, str | None]:
    """Effective credentials: the DB value wins, the env var is the fallback."""
    token = (row.telegram_bot_token if row else None) or settings.TELEGRAM_BOT_TOKEN
    chat_id = (row.telegram_chat_id if row else None) or settings.TELEGRAM_CHAT_ID
    return token, chat_id


def get_effective_telegram_config(db: Session) -> TelegramConfig | None:
    """The effective Telegram config, or None when no credentials exist
    (neither DB nor env provides both a token and a chat id)."""
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    token, chat_id = resolve_telegram_credentials(row)
    if not token or not chat_id:
        return None
    return TelegramConfig(
        token=token,
        chat_id=chat_id,
        enabled=bool(row.telegram_enabled) if row else False,
        min_severity=row.telegram_min_severity if row else "high",
    )


def severity_meets_minimum(severity: str, min_severity: str) -> bool:
    """warning < high < critical (info is below every configurable minimum)."""
    return SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(min_severity, 2)


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    return to_naive_utc(value).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_alert_message(alert: Alert, monitor: Monitor) -> str:
    summary_line = (alert.summary or "").strip().splitlines()[0] if alert.summary else ""
    if len(summary_line) > 200:
        summary_line = summary_line[:197] + "..."
    return (
        f"PulseWatch alert: {alert.title}\n"
        f"Monitor: {monitor.name}\n"
        f"Severity: {alert.severity}\n"
        f"Anomaly: {alert.anomaly_type}\n"
        f"Time: {_format_time(alert.created_at)}\n"
        f"{summary_line}"
    )


def format_recovery_message(
    monitor: Monitor, response_time_ms: float | None, now: datetime
) -> str:
    rt = f"{response_time_ms:.0f} ms" if response_time_ms is not None else "n/a"
    return (
        f"PulseWatch recovery: {monitor.name} is back up\n"
        f"Response time: {rt}\n"
        f"Time: {_format_time(now)}"
    )


async def send_telegram_message(
    config: TelegramConfig,
    text: str,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> bool:
    """POST one plain-text message to the Telegram Bot API.

    Never raises and never logs the token (it is part of the URL).
    Returns True only when Telegram confirms delivery (``{"ok": true}``).
    """
    url = f"{TELEGRAM_API_BASE}/bot{config.token}/sendMessage"
    client = (
        client_factory()
        if client_factory
        else build_async_client(url, timeout=NOTIFY_TIMEOUT_SECONDS)
    )
    try:
        response = await client.post(
            url,
            json={"chat_id": config.chat_id, "text": text},
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            logger.warning(
                "telegram send failed status=%s", response.status_code
            )
            return False
        return bool(response.json().get("ok"))
    except Exception as exc:  # noqa: BLE001 - notification failure is not fatal
        logger.warning("telegram send failed (%s)", type(exc).__name__)
        return False
    finally:
        await client.aclose()


async def notify_new_alert(
    db: Session,
    alert: Alert,
    monitor: Monitor,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> bool:
    """Send the alert notification if enabled and severe enough.
    Returns True only when a message was actually delivered."""
    config = get_effective_telegram_config(db)
    if config is None or not config.enabled:
        return False
    if not severity_meets_minimum(alert.severity, config.min_severity):
        return False
    return await send_telegram_message(
        config, format_alert_message(alert, monitor), client_factory
    )


async def notify_recovery(
    db: Session,
    monitor: Monitor,
    response_time_ms: float | None,
    now: datetime,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> bool:
    """Send a recovery message if notifications are enabled.
    Returns True only when a message was actually delivered."""
    config = get_effective_telegram_config(db)
    if config is None or not config.enabled:
        return False
    return await send_telegram_message(
        config,
        format_recovery_message(monitor, response_time_ms, now),
        client_factory,
    )


async def send_test_notification(
    db: Session,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> tuple[bool, str]:
    """Send the test message. Deliberately ignores the enabled toggle —
    the point of the test button is to verify credentials before enabling.

    Returns ``(success, detail)``; never raises.
    """
    config = get_effective_telegram_config(db)
    if config is None:
        return False, "Telegram not configured"
    sent = await send_telegram_message(config, TEST_MESSAGE, client_factory)
    if sent:
        return True, "Test notification sent"
    return False, "Failed to send test notification"
