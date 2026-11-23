"""Check orchestration: one check end-to-end, plus concurrent batch checks.

Pipeline for a single check:
  1. Load the monitor + recent response-time history (for the historical rule).
  2. Run the real HTTP check (SSRF-validated, redirect-safe).
  3. Store a MonitoringRecord (metadata only — never a response body).
  4. Run the 9 deterministic anomaly rules; store each finding.
  5. Update the monitor's last_* snapshot fields.
  6. Per anomaly: dedup against an open alert, or create a new alert
     (Gemini content when configured, deterministic fallback otherwise).
"""
from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass
from typing import Callable

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, sanitize_url
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.schemas.record import MonitoringRecordOut, record_to_response
from app.services.ai_service import generate_alert_content
from app.services.alert_service import bump_alert, create_alert, find_open_alert
from app.services.anomaly_service import (
    HISTORY_WINDOW,
    AnomalyContext,
    detect_anomalies,
)
from app.services.http_service import find_missing_fields, perform_check
from app.utils.time import utcnow

logger = get_logger("monitoring")


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


async def run_check(
    db: Session,
    monitor_id: int,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ai_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> CheckOutcome:
    """Run one full check for a monitor and persist everything it produces."""
    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        raise MonitorNotFoundError(f"Monitor {monitor_id} not found")

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
        else:
            # Gemini is called ONLY when a new alert is actually created.
            content, ai_generated = await generate_alert_content(
                monitor, finding, metrics, client_factory=ai_client_factory
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
    return CheckOutcome(record=record, anomalies=anomalies, alerts_created=alerts_created)


async def run_batch_checks(
    session_factory: Callable[[], Session],
    monitor_ids: list[int],
    max_concurrency: int | None = None,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ai_client_factory: Callable[[], httpx.AsyncClient] | None = None,
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
                    db, monitor_id, client_factory, ai_client_factory
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
