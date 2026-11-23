"""Check orchestration: one check end-to-end, plus concurrent batch checks.

Pipeline for a single check:
  1. Load the monitor + recent response-time history (for the historical rule).
  2. Run the real HTTP check (SSRF-validated, redirect-safe).
  3. Refresh the TLS cert expiry for https monitors (at most once per 24h;
     failures are ignored — cert lookup never fails a check).
  4. Store a MonitoringRecord (metadata only — never a response body).
  5. Run the 11 deterministic anomaly rules; store each finding.
  6. Update the monitor's last_* snapshot fields + consecutive failures.
  7. Per anomaly: dedup against an open alert, or create a new alert
     (Gemini content when configured, deterministic fallback otherwise).
     On a FAILED check a new alert is created only once the monitor's
     consecutive-failure threshold is reached; dedup bumps are never
     gated, and alerts on successful checks (slow response, zero
     records, ...) are never gated either — consecutive_failures is 0
     by definition on success, so gating them would silence those
     alerts entirely.
  8. After commit, notify: new alerts go to Telegram (when enabled and
     severe enough), and a recovery message goes out when a monitor
     that was down comes back up with an open alert. Notification
     failures never break monitoring.
"""
from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, sanitize_url
from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.schemas.record import MonitoringRecordOut, record_to_response
from app.services.ai_service import generate_alert_content
from app.services.alert_service import (
    OPEN_STATUSES,
    bump_alert,
    create_alert,
    find_open_alert,
)
from app.services.anomaly_service import (
    HISTORY_WINDOW,
    AnomalyContext,
    detect_anomalies,
)
from app.services.http_service import find_missing_fields, perform_check
from app.services.notification_service import notify_new_alert, notify_recovery
from app.services.ssl_service import fetch_cert_expiry, https_host_port
from app.utils.time import to_naive_utc, utcnow

logger = get_logger("monitoring")

# How often a monitor's TLS cert expiry may be re-fetched.
CERT_REFRESH_INTERVAL = timedelta(hours=24)


class MonitorNotFoundError(ValueError):
    pass


@dataclass
class CheckOutcome:
    record: MonitoringRecord
    anomalies: list[Anomaly]
    alerts_created: list[int]


@dataclass
class BatchCheckResult:
    monitor_id: int
    success: bool
    record: MonitoringRecordOut | None = None
    error: str | None = None


def _baseline_stats(history_ms: list[float]) -> dict | None:
    if len(history_ms) < 2:
        return None
    return {
        "n": len(history_ms),
        "mean_ms": statistics.fmean(history_ms),
        "stddev_ms": statistics.stdev(history_ms),
    }


async def _cert_expiry_for_check(
    monitor: Monitor, now: datetime
) -> datetime | None:
    """The cert expiry to evaluate this check's SSL rule against.

    - http URLs: None (SSL monitoring is https-only).
    - https with a fresh (< 24h) cert check: the stored expiry.
    - https with a stale check: fetch in a worker thread (blocking socket
      work must not stall the event loop); on success store the new expiry
      + check time, on failure keep the stored expiry — a transient fetch
      failure must not silence an expiring-cert alert, and an expired cert
      is detected exactly this way (its handshake fails, but the stored
      expiry keeps aging past its date).
    Never raises.
    """
    target = https_host_port(monitor.url)
    if target is None:
        return None
    hostname, port = target
    if monitor.cert_checked_at is not None:
        age = to_naive_utc(now) - to_naive_utc(monitor.cert_checked_at)
        if age < CERT_REFRESH_INTERVAL:
            return monitor.cert_expires_at
    try:
        expiry = await asyncio.to_thread(fetch_cert_expiry, hostname, port)
    except Exception:  # noqa: BLE001 - cert fetch must never break the check
        logger.warning("cert refresh failed monitor_id=%s", monitor.id)
        return monitor.cert_expires_at
    if expiry is None:
        return monitor.cert_expires_at
    monitor.cert_expires_at = expiry
    monitor.cert_checked_at = now
    return expiry


async def _notify_after_check(
    db: Session,
    monitor: Monitor,
    alert_ids: list[int],
    is_success: bool,
    previous_status: str,
    response_time_ms: float | None,
    now: datetime,
    notification_client_factory: Callable[[], httpx.AsyncClient] | None,
) -> None:
    """Telegram notifications for this check. Never raises — every failure
    is caught by the caller, and the notification service itself never
    raises either."""
    for alert_id in alert_ids:
        alert = db.get(Alert, alert_id)
        if alert is not None:
            await notify_new_alert(
                db, alert, monitor, client_factory=notification_client_factory
            )
    if is_success and previous_status == "down":
        has_open_alert = (
            db.query(Alert)
            .filter(
                Alert.monitor_id == monitor.id,
                Alert.status.in_(OPEN_STATUSES),
            )
            .first()
            is not None
        )
        if has_open_alert:
            await notify_recovery(
                db,
                monitor,
                response_time_ms,
                now,
                client_factory=notification_client_factory,
            )


async def run_check(
    db: Session,
    monitor_id: int,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ai_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    notification_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> CheckOutcome:
    """Run one full check for a monitor and persist everything it produces."""
    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        raise MonitorNotFoundError(f"Monitor {monitor_id} not found")
    previous_status = monitor.last_status

    # History is read BEFORE the current record is inserted.
    history_rows = (
        db.query(MonitoringRecord.response_time_ms)
        .filter(
            MonitoringRecord.monitor_id == monitor_id,
            MonitoringRecord.response_time_ms.isnot(None),
        )
        .order_by(MonitoringRecord.checked_at.desc())
        .limit(HISTORY_WINDOW)
        .all()
    )
    history_ms = [row[0] for row in history_rows if row[0] is not None]

    logger.info(
        "check started monitor_id=%s name=%s url=%s",
        monitor.id,
        monitor.name,
        sanitize_url(monitor.url),
    )
    result = await perform_check(monitor, client_factory=client_factory)

    missing_fields = find_missing_fields(result.json_data, monitor.expected_fields or [])
    content_type = (result.content_type or "").lower()
    expected_json = (
        "json" in content_type
        or bool(monitor.expected_fields)
        or bool(monitor.check_zero_records)
    )
    is_success = (
        result.error_kind is None
        and result.status_code is not None
        and result.status_code in (monitor.expected_status_codes or [200])
        and not (expected_json and result.is_valid_json is False)
    )

    now = utcnow()
    # No cert fetch for an SSRF-blocked URL: the policy rejected this host,
    # so the check must not open a connection to it by another path.
    cert_expires_at = (
        await _cert_expiry_for_check(monitor, now)
        if result.error_kind != "ssrf"
        else None
    )

    record = MonitoringRecord(
        monitor_id=monitor.id,
        response_time_ms=result.response_time_ms,
        status_code=result.status_code,
        response_size_bytes=result.response_size_bytes,
        records_returned=result.records_returned,
        is_success=is_success,
        error_message=(result.error_message or "")[:2000] or None,
        checked_at=now,
        content_type=(result.content_type or "")[:255] or None,
        is_valid_json=result.is_valid_json,
    )
    db.add(record)
    db.flush()

    findings = detect_anomalies(
        AnomalyContext(
            response_time_ms=result.response_time_ms,
            latency_threshold_ms=monitor.latency_threshold_ms,
            status_code=result.status_code,
            expected_status_codes=monitor.expected_status_codes or [200],
            error_kind=result.error_kind,
            records_returned=result.records_returned,
            check_zero_records=monitor.check_zero_records,
            is_valid_json=result.is_valid_json,
            expected_json=expected_json,
            missing_fields=missing_fields,
            response_size_bytes=result.response_size_bytes,
            max_response_size_bytes=monitor.max_response_size_bytes,
            history_ms=history_ms,
            cert_expires_at=cert_expires_at,
            now=now,
        )
    )
    anomalies: list[Anomaly] = []
    for finding in findings:
        anomaly = Anomaly(
            monitor_id=monitor.id,
            record_id=record.id,
            anomaly_type=finding.anomaly_type,
            severity=finding.severity,
            description=finding.description,
            detected_at=now,
        )
        db.add(anomaly)
        anomalies.append(anomaly)
    db.flush()

    if is_success:
        monitor.consecutive_failures = 0
    else:
        monitor.consecutive_failures += 1
    monitor.last_checked_at = now
    monitor.last_status = "up" if is_success else "down"
    monitor.last_response_time_ms = result.response_time_ms
    monitor.last_status_code = result.status_code
    db.add(monitor)

    metrics = {
        "status_code": result.status_code,
        "response_time_ms": result.response_time_ms,
        "response_size_bytes": result.response_size_bytes,
        "records_returned": result.records_returned,
        "baseline": _baseline_stats(history_ms),
    }
    # Gate: on a FAILED check, a new alert is created only once the
    # consecutive-failure threshold is reached. Anomalies are still
    # recorded on every failed check, and dedup bumps still happen.
    gate_new_alerts = (
        not is_success
        and monitor.consecutive_failures < monitor.alert_after_failures
    )
    alerts_created: list[int] = []
    for anomaly, finding in zip(anomalies, findings):
        existing = find_open_alert(db, monitor.id, anomaly.anomaly_type)
        if existing is not None:
            bump_alert(db, existing, anomaly)
            logger.info(
                "alert deduped monitor_id=%s anomaly=%s alert_id=%s occurrences=%s",
                monitor.id,
                anomaly.anomaly_type,
                existing.id,
                existing.occurrence_count,
            )
        elif gate_new_alerts:
            logger.info(
                "alert suppressed monitor_id=%s anomaly=%s failures=%s threshold=%s",
                monitor.id,
                anomaly.anomaly_type,
                monitor.consecutive_failures,
                monitor.alert_after_failures,
            )
        else:
            # Gemini is called ONLY when a new alert is actually created.
            content, ai_generated = await generate_alert_content(
                monitor, finding, metrics, client_factory=ai_client_factory
            )
            if not is_success:
                failures = monitor.consecutive_failures
                noun = "check" if failures == 1 else "checks"
                content = content.model_copy(
                    update={
                        "summary": (
                            f"{content.summary} Failed {failures} "
                            f"consecutive {noun}."
                        )
                    }
                )
            alert = create_alert(db, monitor, anomaly, content, ai_generated)
            db.flush()
            alerts_created.append(alert.id)
            logger.info(
                "alert created monitor_id=%s anomaly=%s alert_id=%s ai=%s",
                monitor.id,
                anomaly.anomaly_type,
                alert.id,
                ai_generated,
            )

    db.commit()
    logger.info(
        "check done monitor_id=%s success=%s status=%s rt_ms=%s anomalies=%s alerts=%s",
        monitor.id,
        is_success,
        result.status_code,
        result.response_time_ms,
        len(anomalies),
        len(alerts_created),
    )

    # Notifications run after the commit and must never break monitoring.
    try:
        await _notify_after_check(
            db,
            monitor,
            alerts_created,
            is_success,
            previous_status,
            result.response_time_ms,
            now,
            notification_client_factory,
        )
    except Exception:  # noqa: BLE001 - monitoring already succeeded
        logger.warning(
            "notification step failed monitor_id=%s", monitor.id
        )
    return CheckOutcome(record=record, anomalies=anomalies, alerts_created=alerts_created)


async def run_batch_checks(
    session_factory: Callable[[], Session],
    monitor_ids: list[int],
    max_concurrency: int | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ai_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    notification_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> list[BatchCheckResult]:
    """Check many monitors concurrently (semaphore-bounded).

    Each monitor gets its own DB session and its own try/except, so one
    failure never affects the others (partial success is the point).
    """
    limit = max_concurrency or settings.MAX_CONCURRENCY
    semaphore = asyncio.Semaphore(max(1, limit))

    async def _one(monitor_id: int) -> BatchCheckResult:
        async with semaphore:
            db = session_factory()
            try:
                outcome = await run_check(
                    db,
                    monitor_id,
                    client_factory,
                    ai_client_factory,
                    notification_client_factory,
                )
                # Serialize while the session is still open (lazy relationships).
                return BatchCheckResult(
                    monitor_id=monitor_id,
                    success=True,
                    record=record_to_response(outcome.record),
                )
            except MonitorNotFoundError:
                return BatchCheckResult(
                    monitor_id=monitor_id,
                    success=False,
                    error=f"Monitor {monitor_id} not found",
                )
            except Exception as exc:  # noqa: BLE001 - batch must never fail wholesale
                logger.exception("batch check failed monitor_id=%s", monitor_id)
                return BatchCheckResult(
                    monitor_id=monitor_id, success=False, error=str(exc)
                )
            finally:
                db.close()

    return list(await asyncio.gather(*[_one(mid) for mid in monitor_ids]))
