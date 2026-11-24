"""Batch checks: partial success, and the concurrency demonstration.

The concurrency test is the scalability proof: N monitors with an artificial
per-check delay must complete in far less than N x delay when run with a
high concurrency limit, and in ~N x delay when limited to 1.
"""
from __future__ import annotations

import time

import pytest

from app.database.connection import SessionLocal
from app.services.monitoring_service import run_batch_checks
from tests.conftest import json_response_handler, mock_client_factory


async def test_batch_partial_success_mixed_valid_and_invalid_ids(db, make_monitor):
    m1 = make_monitor(name="M1")
    m2 = make_monitor(name="M2")
    factory = mock_client_factory(json_response_handler(payload=[{"id": 1}]))

    results = await run_batch_checks(
        SessionLocal, [m1.id, 999999, m2.id], client_factory=factory
    )

    assert len(results) == 3
    by_id = {r.monitor_id: r for r in results}
    assert by_id[m1.id].success is True
    assert by_id[m1.id].record is not None
    assert by_id[m1.id].record.monitor_id == m1.id
    assert by_id[m2.id].success is True
    assert by_id[999999].success is False
    assert by_id[999999].record is None
    assert "not found" in by_id[999999].error
    assert sum(1 for r in results if r.success) == 2
    assert sum(1 for r in results if not r.success) == 1


async def test_batch_one_failing_check_does_not_break_others(db, make_monitor):
    m1 = make_monitor(name="Good")
    m2 = make_monitor(name="Bad", url="http://127.0.0.1:9/blocked")  # SSRF-blocked
    factory = mock_client_factory(json_response_handler(payload=[{"id": 1}]))

    results = await run_batch_checks(
        SessionLocal, [m1.id, m2.id], client_factory=factory
    )

    by_id = {r.monitor_id: r for r in results}
    # Both "succeed" as batch items (the check ran); the blocked one simply
    # recorded a failed check.
    assert by_id[m1.id].success is True
    assert by_id[m2.id].success is True
    assert by_id[m1.id].record.is_success is True
    assert by_id[m2.id].record.is_success is False


async def test_batch_concurrency_proves_parallel_execution(db, make_monitor):
    """5 monitors x 0.3s artificial delay: sequential would take ~1.5s.
    With max_concurrency=5 the batch must finish well under that."""
    monitors = [make_monitor(name=f"M{i}") for i in range(5)]
    factory = mock_client_factory(json_response_handler(delay=0.3))

    started = time.perf_counter()
    results = await run_batch_checks(
        SessionLocal,
        [m.id for m in monitors],
        max_concurrency=5,
        client_factory=factory,
    )
    elapsed = time.perf_counter() - started

    assert all(r.success for r in results)
    assert len(results) == 5
    assert elapsed < 1.0, f"batch took {elapsed:.2f}s; expected well under 1.5s"


async def test_batch_concurrency_limit_is_respected(db, make_monitor):
    """With max_concurrency=1 the same 3 x 0.2s batch must take ~0.6s
    (sequential), proving the semaphore actually bounds parallelism."""
    monitors = [make_monitor(name=f"M{i}") for i in range(3)]
    factory = mock_client_factory(json_response_handler(delay=0.2))

    started = time.perf_counter()
    results = await run_batch_checks(
        SessionLocal,
        [m.id for m in monitors],
        max_concurrency=1,
        client_factory=factory,
    )
    elapsed = time.perf_counter() - started

    assert all(r.success for r in results)
    assert elapsed >= 0.55, f"batch took {elapsed:.2f}s; expected ~0.6s sequential"


# --- POST /api/monitoring/batch (route level) -------------------------------

def test_api_batch_skips_unknown_ids_and_reports_counts(client, db, make_monitor, monkeypatch):
    """Route level: unknown ids are silently skipped (v4 scoping — the
    route keeps only monitors the caller owns before running the batch),
    so results contain only the owned monitors. Partial-success
    semantics for unknown ids live at the service level; see
    test_batch_partial_success_mixed_valid_and_invalid_ids."""
    import app.api.routes.monitoring as monitoring_route
    from app.services import monitoring_service

    m1 = make_monitor(name="M1")
    m2 = make_monitor(name="M2")
    factory = mock_client_factory(json_response_handler(payload=[{"id": 1}]))

    async def run_batch_with_mock(session_factory, ids, max_concurrency=None, **kwargs):
        return await monitoring_service.run_batch_checks(
            session_factory, ids, max_concurrency, client_factory=factory
        )

    monkeypatch.setattr(monitoring_route, "run_batch_checks", run_batch_with_mock)

    response = client.post(
        "/api/monitoring/batch",
        json={"monitor_ids": [m1.id, 999999, m2.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert len(body["results"]) == 2  # 999999 silently skipped
    assert {r["monitor_id"] for r in body["results"]} == {m1.id, m2.id}
    assert body["elapsed_ms"] >= 0


def test_api_batch_dedupes_ids(client, db, make_monitor, monkeypatch):
    import app.api.routes.monitoring as monitoring_route
    from app.services import monitoring_service

    m1 = make_monitor(name="M1")
    factory = mock_client_factory(json_response_handler(payload=[{"id": 1}]))

    async def run_batch_with_mock(session_factory, ids, max_concurrency=None, **kwargs):
        return await monitoring_service.run_batch_checks(
            session_factory, ids, max_concurrency, client_factory=factory
        )

    monkeypatch.setattr(monitoring_route, "run_batch_checks", run_batch_with_mock)

    response = client.post(
        "/api/monitoring/batch", json={"monitor_ids": [m1.id, m1.id, m1.id]}
    )
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1
    assert response.json()["succeeded"] == 1


@pytest.mark.parametrize("monitor_ids", [[], list(range(1, 52))])
def test_api_batch_rejects_empty_and_oversized_lists(client, monitor_ids):
    response = client.post("/api/monitoring/batch", json={"monitor_ids": monitor_ids})
    assert response.status_code == 422
