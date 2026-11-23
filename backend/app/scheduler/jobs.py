"""APScheduler jobs: one interval job per active monitor, plus a daily
retention-cleanup job at 03:00 UTC.

- Single module-level AsyncIOScheduler, started only from the lifespan hook
  (never on import, never under pytest — see main.py's TESTING guard).
- Job ids are ``monitor_<id>``; max_instances=1, coalesce=True,
  misfire_grace_time = the monitor's interval. The cleanup job id is
  ``retention_cleanup``.
- All reschedule helpers are no-ops while the scheduler is not running, so
  monitor CRUD stays safe in tests and before startup.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.database.connection import SessionLocal
from app.models.monitor import Monitor
from app.services.monitoring_service import run_check
from app.services.retention_service import run_cleanup

logger = get_logger("scheduler")

scheduler = AsyncIOScheduler()

CLEANUP_JOB_ID = "retention_cleanup"


def job_id(monitor_id: int) -> str:
    return f"monitor_{monitor_id}"


async def run_scheduled_check(monitor_id: int) -> None:
    """Job function: same check pipeline as a manual check."""
    db = SessionLocal()
    try:
        monitor = db.get(Monitor, monitor_id)
        if monitor is None:
            unschedule_monitor(monitor_id)
            return
        if not monitor.is_active:
            return
        await run_check(db, monitor_id)
    except Exception:
        logger.exception("scheduled check failed monitor_id=%s", monitor_id)
    finally:
        db.close()


def schedule_monitor(monitor_id: int, interval_seconds: int) -> None:
    if not scheduler.running:
        return
    scheduler.add_job(
        run_scheduled_check,
        trigger=IntervalTrigger(seconds=interval_seconds),
        args=[monitor_id],
        id=job_id(monitor_id),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=interval_seconds,
    )
    logger.info(
        "monitor job scheduled monitor_id=%s interval=%ss", monitor_id, interval_seconds
    )


def unschedule_monitor(monitor_id: int) -> None:
    if not scheduler.running:
        return
    if scheduler.get_job(job_id(monitor_id)) is not None:
        scheduler.remove_job(job_id(monitor_id))
        logger.info("monitor job removed monitor_id=%s", monitor_id)


def reschedule_monitor(monitor: Monitor) -> None:
    """Call after monitor create/update/toggle/delete (delete: call
    unschedule_monitor directly)."""
    if monitor.is_active:
        schedule_monitor(monitor.id, monitor.interval_seconds)
    else:
        unschedule_monitor(monitor.id)


async def run_retention_cleanup() -> None:
    """Job function: delete expired records and old resolved alerts."""
    db = SessionLocal()
    try:
        counts = run_cleanup(db)
        logger.info(
            "retention cleanup done records=%s alerts=%s anomalies=%s",
            counts["records_deleted"],
            counts["alerts_deleted"],
            counts["anomalies_deleted"],
        )
    except Exception:
        logger.exception("retention cleanup failed")
    finally:
        db.close()


def schedule_retention_cleanup() -> None:
    """Register the daily 03:00 UTC cleanup job (no-op if not running)."""
    if not scheduler.running:
        return
    scheduler.add_job(
        run_retention_cleanup,
        trigger=CronTrigger(hour=3, minute=0),
        id=CLEANUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("retention cleanup job scheduled (daily 03:00 UTC)")


def sync_all_jobs(db: Session) -> None:
    """(Re)create jobs for every active monitor. Scheduler must be running."""
    monitors = db.query(Monitor).filter(Monitor.is_active.is_(True)).all()
    for monitor in monitors:
        schedule_monitor(monitor.id, monitor.interval_seconds)
    logger.info("scheduler synced %d monitor jobs", len(monitors))


def start_scheduler(db: Session) -> None:
    if scheduler.running:
        return
    scheduler.start()
    sync_all_jobs(db)
    schedule_retention_cleanup()
    logger.info("scheduler started")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")
