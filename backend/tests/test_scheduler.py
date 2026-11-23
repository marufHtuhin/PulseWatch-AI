"""Scheduler: job registration / rescheduling on monitor lifecycle events.

The scheduler service functions are tested directly against a fresh
``AsyncIOScheduler`` instance (monkeypatched in place of the module-level
one), never through the app lifespan — the module-level scheduler stays
stopped throughout the test suite.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.monitoring_record import MonitoringRecord
from app.scheduler import jobs


@pytest.fixture()
async def test_scheduler(monkeypatch):
    """A fresh scheduler instance swapped in for ``jobs.scheduler``.

    It is yielded NOT started: tests either start it themselves or exercise
    ``start_scheduler`` (which starts it). Teardown shuts it down if running.
    """
    scheduler = AsyncIOScheduler()
    monkeypatch.setattr(jobs, "scheduler", scheduler)
    try:
        yield scheduler
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


def _job_for(scheduler, monitor_id: int):
    return scheduler.get_job(jobs.job_id(monitor_id))


async def test_start_scheduler_registers_jobs_for_active_monitors_only(
    db, make_monitor, test_scheduler
):
    active1 = make_monitor(name="A1", interval_seconds=300)
    active2 = make_monitor(name="A2", interval_seconds=60)
    make_monitor(name="Paused", is_active=False)

    jobs.start_scheduler(db)

    assert test_scheduler.running is True
    job1 = _job_for(test_scheduler, active1.id)
    job2 = _job_for(test_scheduler, active2.id)
    assert job1 is not None
    assert job2 is not None
    # The inactive monitor has no job. The third job is the daily
    # retention cleanup (03:00 UTC).
    assert len(test_scheduler.get_jobs()) == 3
    cleanup_job = test_scheduler.get_job(jobs.CLEANUP_JOB_ID)
    assert cleanup_job is not None
    assert cleanup_job.func is jobs.run_retention_cleanup
    # CronTrigger renders as cron[hour='3', minute='0'].
    assert "hour='3'" in str(cleanup_job.trigger)
    assert "minute='0'" in str(cleanup_job.trigger)
    # Trigger interval matches the monitor's interval.
    assert job1.trigger.interval == timedelta(seconds=300)
    assert job2.trigger.interval == timedelta(seconds=60)
    # Contract guarantees: single instance, coalesced, misfire grace = interval.
    assert job1.max_instances == 1
    assert job1.coalesce is True
    assert job1.misfire_grace_time == 300
    assert job1.func is jobs.run_scheduled_check
    assert job1.args == (active1.id,)  # APScheduler stores args as a tuple


async def test_schedule_monitor_twice_creates_no_duplicate_job(
    db, make_monitor, test_scheduler
):
    test_scheduler.start()
    monitor = make_monitor(interval_seconds=300)
    jobs.schedule_monitor(monitor.id, 300)
    jobs.schedule_monitor(monitor.id, 300)
    jobs.schedule_monitor(monitor.id, 300)

    assert len(test_scheduler.get_jobs()) == 1
    assert _job_for(test_scheduler, monitor.id) is not None


async def test_reschedule_updates_interval_and_removes_when_paused(
    db, make_monitor, test_scheduler
):
    test_scheduler.start()
    monitor = make_monitor(interval_seconds=300)
    jobs.reschedule_monitor(monitor)

    assert _job_for(test_scheduler, monitor.id).trigger.interval == timedelta(
        seconds=300
    )

    # Interval change: same job id, new trigger.
    monitor.interval_seconds = 60
    db.commit()
    jobs.reschedule_monitor(monitor)
    assert len(test_scheduler.get_jobs()) == 1
    assert _job_for(test_scheduler, monitor.id).trigger.interval == timedelta(
        seconds=60
    )

    # Pausing removes the job.
    monitor.is_active = False
    db.commit()
    jobs.reschedule_monitor(monitor)
    assert _job_for(test_scheduler, monitor.id) is None
    assert test_scheduler.get_jobs() == []

    # Re-activating re-adds it.
    monitor.is_active = True
    db.commit()
    jobs.reschedule_monitor(monitor)
    assert _job_for(test_scheduler, monitor.id) is not None


async def test_unschedule_removes_job_and_is_safe_when_absent(
    db, make_monitor, test_scheduler
):
    test_scheduler.start()
    monitor = make_monitor()
    jobs.schedule_monitor(monitor.id, 300)
    assert _job_for(test_scheduler, monitor.id) is not None

    jobs.unschedule_monitor(monitor.id)
    assert _job_for(test_scheduler, monitor.id) is None

    # Removing a job that does not exist must not raise.
    jobs.unschedule_monitor(monitor.id)
    jobs.unschedule_monitor(999999)


async def test_start_scheduler_is_idempotent(db, make_monitor, test_scheduler):
    make_monitor(interval_seconds=300)
    jobs.start_scheduler(db)
    jobs.start_scheduler(db)  # second call is a no-op
    # 1 monitor job + the daily retention cleanup job.
    assert len(test_scheduler.get_jobs()) == 2


async def test_reschedule_helpers_are_noops_when_scheduler_stopped(db, make_monitor):
    """Before startup (and under pytest) CRUD must not touch the scheduler."""
    assert jobs.scheduler.running is False
    monitor = make_monitor()
    jobs.schedule_monitor(monitor.id, 300)
    jobs.reschedule_monitor(monitor)
    jobs.unschedule_monitor(monitor.id)
    # No exception, and the module-level scheduler is still stopped.
    assert jobs.scheduler.running is False


async def test_scheduled_check_for_deleted_monitor_removes_its_job(
    db, make_monitor, test_scheduler
):
    test_scheduler.start()
    monitor = make_monitor()
    jobs.schedule_monitor(monitor.id, 300)
    assert _job_for(test_scheduler, monitor.id) is not None

    db.delete(monitor)
    db.commit()
    await jobs.run_scheduled_check(monitor.id)

    assert _job_for(test_scheduler, monitor.id) is None


async def test_scheduled_check_skips_inactive_monitor(
    db, make_monitor, test_scheduler
):
    test_scheduler.start()
    monitor = make_monitor(is_active=False)
    await jobs.run_scheduled_check(monitor.id)
    # No check was performed: no record was created.
    assert db.query(MonitoringRecord).count() == 0


async def test_sync_all_jobs_recreates_jobs_for_active_monitors(
    db, make_monitor, test_scheduler
):
    test_scheduler.start()
    m1 = make_monitor(name="A1", interval_seconds=300)
    make_monitor(name="Paused", is_active=False)

    jobs.sync_all_jobs(db)

    assert len(test_scheduler.get_jobs()) == 1
    assert _job_for(test_scheduler, m1.id) is not None

    # Syncing again does not duplicate.
    jobs.sync_all_jobs(db)
    assert len(test_scheduler.get_jobs()) == 1
