"""Latency percentiles: the interpolation math, and the summary/health
API fields built on it (successful checks only, 24h window, null on no data)."""
from __future__ import annotations

from datetime import timedelta

from app.models.monitoring_record import MonitoringRecord
from app.services.dashboard_service import percentile
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


# --- the math ---------------------------------------------------------------

def test_percentile_empty_list_is_none():
    assert percentile([], 50) is None
    assert percentile([], 99) is None


def test_percentile_single_value_returns_itself():
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 95) == 42.0
    assert percentile([42.0], 99) == 42.0


def test_percentile_odd_count_picks_the_middle():
    # [10, 20, 30]: p50 rank = 1.0 -> exactly the middle value.
    assert percentile([10.0, 20.0, 30.0], 50) == 20.0
    # p90 rank = 1.8 -> 20 + 0.8 * (30 - 20) = 28.
    assert percentile([10.0, 20.0, 30.0], 90) == 28.0


def test_percentile_even_count_interpolates():
    import pytest

    # [100, 200, 300, 400]: p50 rank = 1.5 -> 250.
    assert percentile([100.0, 200.0, 300.0, 400.0], 50) == 250.0
    # p95 rank = 2.85 -> 300 + 0.85 * 100 = 385.
    assert percentile([100.0, 200.0, 300.0, 400.0], 95) == pytest.approx(385.0)
    # p99 rank = 2.97 -> 300 + 0.97 * 100 = 397.
    assert percentile([100.0, 200.0, 300.0, 400.0], 99) == pytest.approx(397.0)


def test_percentile_sorts_unsorted_input():
    assert percentile([400.0, 100.0, 300.0, 200.0], 50) == 250.0


def test_percentile_matches_statistics_quantiles_inclusive():
    """Cross-check against the stdlib's inclusive method (same definition)."""
    import statistics

    import pytest

    data = [7.0, 15.0, 36.0, 39.0, 40.0, 41.0]
    inclusive = statistics.quantiles(data, n=100, method="inclusive")
    assert percentile(data, 50) == pytest.approx(inclusive[49])  # 50th
    assert percentile(data, 95) == pytest.approx(inclusive[94])  # 95th
    assert percentile(data, 99) == pytest.approx(inclusive[98])  # 99th


# --- summary API ------------------------------------------------------------

def _seed_scenario(db, make_monitor):
    """4 successful checks (100–400ms) + 1 failed (500ms) in 24h + 1 stale."""
    m_up = make_monitor(name="Up API")
    m_down = make_monitor(name="Down API")
    m_unknown = make_monitor(name="Never checked")
    _seed_record(db, m_up.id, rt_ms=100.0, success=True, minutes_ago=10)
    _seed_record(db, m_up.id, rt_ms=200.0, success=True, minutes_ago=20)
    _seed_record(db, m_up.id, rt_ms=300.0, success=True, minutes_ago=30)
    _seed_record(db, m_down.id, rt_ms=400.0, success=True, minutes_ago=40)
    _seed_record(db, m_down.id, rt_ms=500.0, success=False, minutes_ago=50)
    _seed_record(db, m_up.id, rt_ms=9999.0, success=False, hours_ago=25)
    db.commit()
    return m_up, m_down, m_unknown


def test_summary_percentiles_from_successful_checks_only(client, db, make_monitor):
    _seed_scenario(db, make_monitor)

    body = client.get("/api/dashboard/summary").json()

    # Successful RTs in 24h: [100, 200, 300, 400]. The failed 500ms check
    # and the stale 9999ms check are both excluded (with the failed one
    # included, p50 would be 300, not 250).
    assert body["p50_response_time_ms"] == 250.0
    assert body["p95_response_time_ms"] == 385.0
    assert body["p99_response_time_ms"] == 397.0


def test_summary_percentiles_are_null_without_data(client):
    body = client.get("/api/dashboard/summary").json()
    assert body["p50_response_time_ms"] is None
    assert body["p95_response_time_ms"] is None
    assert body["p99_response_time_ms"] is None


def test_summary_percentiles_null_when_only_failed_checks_exist(
    client, db, make_monitor
):
    monitor = make_monitor()
    _seed_record(db, monitor.id, rt_ms=500.0, success=False, minutes_ago=5)
    db.commit()

    body = client.get("/api/dashboard/summary").json()
    # No successful checks -> null, never 0.
    assert body["p50_response_time_ms"] is None
    assert body["p95_response_time_ms"] is None
    assert body["p99_response_time_ms"] is None


# --- health API -------------------------------------------------------------

def test_health_p95_per_monitor(client, db, make_monitor):
    m_up, m_down, m_unknown = _seed_scenario(db, make_monitor)

    items = {m["monitor_id"]: m for m in client.get("/api/dashboard/health").json()["monitors"]}

    # Up: successful [100, 200, 300] -> p95 rank 1.9 -> 290.
    assert items[m_up.id]["p95_response_time_ms"] == 290.0
    # Down: only one successful check (400ms); the failed 500ms is excluded.
    assert items[m_down.id]["p95_response_time_ms"] == 400.0
    # Unknown: no checks at all.
    assert items[m_unknown.id]["p95_response_time_ms"] is None
