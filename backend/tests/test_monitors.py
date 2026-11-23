"""Monitor CRUD, validation, filters, secret-header masking, cascade delete."""
from __future__ import annotations

import pytest

from app.models.alert import Alert
from app.models.anomaly import Anomaly
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.services.monitoring_service import run_check
from tests.conftest import (
    TEST_URL,
    json_response_handler,
    mock_client_factory,
    monitor_payload,
)


# --- create -----------------------------------------------------------------

def test_create_monitor_returns_201_with_defaults(client):
    response = client.post(
        "/api/monitors", json={"name": "Minimal", "url": TEST_URL}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Minimal"
    assert body["url"] == TEST_URL
    assert body["method"] == "GET"
    assert body["timeout_seconds"] == 10
    assert body["interval_seconds"] == 300
    assert body["expected_status_codes"] == [200]
    assert body["expected_fields"] == []
    assert body["check_zero_records"] is False
    assert body["latency_threshold_ms"] == 3000
    assert body["max_response_size_bytes"] == 1048576
    assert body["is_active"] is True
    assert body["last_status"] == "unknown"
    assert body["last_checked_at"] is None
    assert body["created_at"] is not None


def test_create_monitor_strips_url_whitespace(client):
    response = client.post(
        "/api/monitors",
        json=monitor_payload(url="  https://example.com/api  "),
    )
    assert response.status_code == 201
    assert response.json()["url"] == "https://example.com/api"


@pytest.mark.parametrize(
    "overrides",
    [
        {"url": "not-a-url"},
        {"url": "ftp://example.com/file"},
        {"url": "example.com/no-scheme"},
        {"url": "https://"},  # no hostname
        {"method": "FETCH"},
        {"method": "get"},  # lowercase is not a valid method literal
        {"interval_seconds": 45},
        {"interval_seconds": 60 * 60},
        {"timeout_seconds": 0},
        {"timeout_seconds": 121},
        {"latency_threshold_ms": 0},
        {"max_response_size_bytes": 0},
        {"expected_status_codes": []},
        {"expected_status_codes": [99]},
        {"expected_status_codes": [600]},
    ],
)
def test_create_monitor_rejects_invalid_input(client, overrides):
    response = client.post("/api/monitors", json=monitor_payload(**overrides))
    assert response.status_code == 422, response.text


def test_create_monitor_requires_name_and_url(client):
    assert client.post("/api/monitors", json={"url": TEST_URL}).status_code == 422
    assert client.post("/api/monitors", json={"name": "No URL"}).status_code == 422
    assert client.post("/api/monitors", json={}).status_code == 422


# --- list / get -------------------------------------------------------------

def test_list_monitors_pagination_and_envelope(client, create_monitor_via_api):
    for i in range(5):
        create_monitor_via_api(name=f"API {i}")

    page1 = client.get("/api/monitors", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200
    body = page1.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2

    page3 = client.get("/api/monitors", params={"page": 3, "page_size": 2})
    assert len(page3.json()["items"]) == 1  # last partial page

    page_size_capped = client.get("/api/monitors", params={"page_size": 101})
    assert page_size_capped.status_code == 422
    assert client.get("/api/monitors", params={"page": 0}).status_code == 422


def test_list_monitors_search_filter(client, create_monitor_via_api):
    create_monitor_via_api(name="Posts API", url="https://example.com/posts")
    create_monitor_via_api(name="Users API", url="https://example.com/users")

    by_name = client.get("/api/monitors", params={"search": "Posts"})
    assert by_name.json()["total"] == 1
    assert by_name.json()["items"][0]["name"] == "Posts API"

    by_url = client.get("/api/monitors", params={"search": "users"})
    assert by_url.json()["total"] == 1

    no_match = client.get("/api/monitors", params={"search": "zzz-no-such"})
    assert no_match.json()["total"] == 0


def test_list_monitors_active_and_status_filters(
    client, create_monitor_via_api, db
):
    active = create_monitor_via_api(name="Active one")
    create_monitor_via_api(name="Paused one", is_active=False)
    # Flip one monitor's last_status directly so the status filter has data.
    row = db.get(Monitor, active["id"])
    row.last_status = "down"
    db.commit()

    assert client.get("/api/monitors", params={"is_active": True}).json()["total"] == 1
    assert client.get("/api/monitors", params={"is_active": False}).json()["total"] == 1
    down = client.get("/api/monitors", params={"status": "down"}).json()
    assert down["total"] == 1
    assert down["items"][0]["name"] == "Active one"
    assert client.get("/api/monitors", params={"status": "up"}).json()["total"] == 0
    assert client.get("/api/monitors", params={"status": "bogus"}).status_code == 422


def test_get_monitor_and_404(client, create_monitor_via_api):
    created = create_monitor_via_api(name="Get me")
    response = client.get(f"/api/monitors/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Get me"

    missing = client.get("/api/monitors/999999")
    assert missing.status_code == 404


# --- update / toggle / delete -----------------------------------------------

def test_full_update_replaces_fields(client, create_monitor_via_api):
    created = create_monitor_via_api(name="Before")
    response = client.put(
        f"/api/monitors/{created['id']}",
        json=monitor_payload(
            name="After",
            url="https://example.com/other",
            method="POST",
            timeout_seconds=5,
            interval_seconds=60,
            expected_status_codes=[200, 201],
            expected_fields=["id"],
            check_zero_records=True,
            latency_threshold_ms=500,
            is_active=False,
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "After"
    assert body["url"] == "https://example.com/other"
    assert body["method"] == "POST"
    assert body["timeout_seconds"] == 5
    assert body["interval_seconds"] == 60
    assert body["expected_status_codes"] == [200, 201]
    assert body["expected_fields"] == ["id"]
    assert body["check_zero_records"] is True
    assert body["latency_threshold_ms"] == 500
    assert body["is_active"] is False


def test_update_validates_and_404s(client, create_monitor_via_api):
    created = create_monitor_via_api()
    bad = client.put(
        f"/api/monitors/{created['id']}", json=monitor_payload(url="notaurl")
    )
    assert bad.status_code == 422
    missing = client.put("/api/monitors/999999", json=monitor_payload())
    assert missing.status_code == 404


def test_toggle_flips_is_active(client, create_monitor_via_api):
    created = create_monitor_via_api(is_active=True)
    first = client.patch(f"/api/monitors/{created['id']}/toggle")
    assert first.status_code == 200
    assert first.json()["is_active"] is False
    second = client.patch(f"/api/monitors/{created['id']}/toggle")
    assert second.json()["is_active"] is True
    assert client.patch("/api/monitors/999999/toggle").status_code == 404


async def test_delete_cascades_records_anomalies_alerts(
    client, db, make_monitor
):
    # A failing check seeds a record + anomaly + alert for the monitor.
    monitor = make_monitor()
    monitor_id = monitor.id  # capture before the row is deleted
    factory = mock_client_factory(json_response_handler(status=500, payload={}))
    await run_check(db, monitor_id, client_factory=factory)
    assert db.query(MonitoringRecord).count() == 1
    assert db.query(Anomaly).count() >= 1
    assert db.query(Alert).count() >= 1

    response = client.delete(f"/api/monitors/{monitor_id}")
    assert response.status_code == 204
    assert response.content == b""

    # The delete ran in the API's session; expire this session's cached rows
    # so the assertions below read fresh state from the database.
    db.expire_all()
    assert db.get(Monitor, monitor_id) is None
    assert db.query(MonitoringRecord).count() == 0
    assert db.query(Anomaly).count() == 0
    assert db.query(Alert).count() == 0
    assert client.get(f"/api/monitors/{monitor_id}").status_code == 404
    assert client.delete("/api/monitors/999999").status_code == 404


# --- secret-header masking --------------------------------------------------

def test_secret_headers_masked_in_responses(client, create_monitor_via_api):
    created = create_monitor_via_api(
        headers={
            "Authorization": "Bearer super-secret",
            "X-Api-Key": "key-123",
            "Cookie": "session=abc",
            "Accept": "application/json",
        }
    )
    headers = created["headers"]
    assert headers["Authorization"] == "********"
    assert headers["X-Api-Key"] == "********"
    assert headers["Cookie"] == "********"
    assert headers["Accept"] == "application/json"  # non-secret untouched

    fetched = client.get(f"/api/monitors/{created['id']}").json()
    assert fetched["headers"]["Authorization"] == "********"


def test_secret_headers_masked_case_insensitively(client, create_monitor_via_api):
    created = create_monitor_via_api(headers={"AUTHORIZATION": "Bearer x"})
    assert created["headers"]["AUTHORIZATION"] == "********"


def test_update_with_masked_value_keeps_stored_secret(
    client, create_monitor_via_api, db
):
    created = create_monitor_via_api(
        headers={"Authorization": "Bearer original", "Accept": "application/json"}
    )
    # Send back exactly what the API returned: "********" means "keep it".
    response = client.put(
        f"/api/monitors/{created['id']}",
        json=monitor_payload(
            headers={"Authorization": "********", "Accept": "application/json"}
        ),
    )
    assert response.status_code == 200
    assert response.json()["headers"]["Authorization"] == "********"

    stored = db.get(Monitor, created["id"])
    assert stored.headers["Authorization"] == "Bearer original"


def test_update_with_new_secret_replaces_it(client, create_monitor_via_api, db):
    created = create_monitor_via_api(headers={"Authorization": "Bearer old"})
    response = client.put(
        f"/api/monitors/{created['id']}",
        json=monitor_payload(headers={"Authorization": "Bearer new"}),
    )
    assert response.status_code == 200
    stored = db.get(Monitor, created["id"])
    assert stored.headers["Authorization"] == "Bearer new"


def test_update_can_remove_headers_entirely(client, create_monitor_via_api, db):
    created = create_monitor_via_api(headers={"Authorization": "Bearer old"})
    response = client.put(
        f"/api/monitors/{created['id']}", json=monitor_payload(headers=None)
    )
    assert response.status_code == 200
    assert response.json()["headers"] == {}
    assert db.get(Monitor, created["id"]).headers == {}
