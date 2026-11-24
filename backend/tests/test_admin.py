"""Admin role + admin panel (v4.2): /api/admin/* endpoints, the admin
bootstrap promotion, and /me's is_admin flag.

Contract under test (see API_CONTRACT.md "Admin"):
- The ADMIN_EMAIL account is the admin: the startup bootstrap promotes
  an existing user with that email to is_admin=true, or creates the
  account (as admin) when none exists.
- Six admin endpoints, all requiring an admin token:
  GET /api/admin/stats, GET /api/admin/users, GET /api/admin/users/{id},
  PATCH /api/admin/users/{id} ({is_active}), DELETE /api/admin/users/{id},
  GET /api/admin/monitors (?user_id= filter).
- Non-admin -> 403 on every admin endpoint; no token -> 401.
- Admins cannot deactivate or delete themselves or another admin (400).
- Deleting a user cascades to their monitors, alerts, and records.
- List endpoints follow the codebase convention: a paginated envelope
  {items, total, page, page_size}. Stats uses the dashboard naming
  convention: total_users / total_monitors / total_alerts.
"""
from __future__ import annotations

from app.core.auth import bootstrap_admin
from app.core.config import settings
from app.models.alert import Alert
from app.models.monitor import Monitor
from app.models.monitoring_record import MonitoringRecord
from app.models.user import User
from tests.conftest import TEST_USER_PASSWORD, register_user

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-password-123"
PASSWORD = TEST_USER_PASSWORD


# --- helpers ----------------------------------------------------------------

def _make_admin(anon_client, db, email=ADMIN_EMAIL) -> dict:
    """Register a user via the API, then flip is_admin in the DB.

    The registration token stays valid: get_current_user loads the user
    (and is_admin) fresh from the DB on every request, so a flag set
    after the token was issued is honoured immediately.
    """
    user = register_user(anon_client, email=email, password=ADMIN_PASSWORD)
    row = db.query(User).filter(User.email == email).first()
    assert row is not None
    row.is_admin = True
    db.commit()
    return user


def _make_monitor_row(db, user_id, name="Example API") -> Monitor:
    """Insert a Monitor row directly (no client fixture, so user counts
    stay exact in the stats/users tests)."""
    monitor = Monitor(
        name=name,
        url="https://example.com/api",
        method="GET",
        timeout_seconds=10,
        interval_seconds=300,
        expected_status_codes=[200],
        expected_fields=[],
        check_zero_records=False,
        latency_threshold_ms=3000,
        max_response_size_bytes=1048576,
        is_active=True,
        user_id=user_id,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def _seed_alert(db, monitor_id) -> Alert:
    alert = Alert(
        monitor_id=monitor_id,
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
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def _seed_record(db, monitor_id) -> MonitoringRecord:
    record = MonitoringRecord(
        monitor_id=monitor_id,
        response_time_ms=100.0,
        status_code=200,
        response_size_bytes=100,
        records_returned=1,
        is_success=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _enable_bootstrap(monkeypatch):
    """Bootstrap is skipped while TESTING; opt back in (same pattern as
    test_auth.py's bootstrap tests)."""
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", ADMIN_PASSWORD)


# --- bootstrap --------------------------------------------------------------

def test_bootstrap_promotes_existing_admin_email_user(
    db, anon_client, monkeypatch
):
    """A normal user who already has the ADMIN_EMAIL address becomes an
    admin on the first v4.2 boot — no duplicate account is created."""
    register_user(anon_client, email=ADMIN_EMAIL, password=PASSWORD)
    user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    assert user is not None
    assert user.is_admin is False

    _enable_bootstrap(monkeypatch)
    bootstrap_admin(db)
    db.expire_all()

    user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    assert user.is_admin is True
    assert db.query(User).filter(User.email == ADMIN_EMAIL).count() == 1


def test_bootstrap_creates_fresh_admin_user(db, anon_client, monkeypatch):
    """No user with the ADMIN_EMAIL address exists: bootstrap creates
    the account as an admin, and it can log in with ADMIN_PASSWORD."""
    assert db.query(User).filter(User.email == ADMIN_EMAIL).first() is None

    _enable_bootstrap(monkeypatch)
    bootstrap_admin(db)
    db.expire_all()

    user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    assert user is not None
    assert user.is_admin is True
    assert user.is_active is True

    login = anon_client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200

    # Idempotent: a second run creates no second admin user.
    bootstrap_admin(db)
    assert db.query(User).filter(User.email == ADMIN_EMAIL).count() == 1


# --- authorization: 403 / 401 ------------------------------------------------

def test_non_admin_gets_403_on_every_admin_endpoint(db, anon_client):
    user = register_user(anon_client, email="normal@example.com", password=PASSWORD)
    cases = [
        ("GET", "/api/admin/stats", None),
        ("GET", "/api/admin/users", None),
        ("GET", f"/api/admin/users/{user['id']}", None),
        ("PATCH", f"/api/admin/users/{user['id']}", {"is_active": False}),
        ("DELETE", f"/api/admin/users/{user['id']}", None),
        ("GET", "/api/admin/monitors", None),
    ]
    for method, path, payload in cases:
        response = anon_client.request(
            method, path, json=payload, headers=user["headers"]
        )
        assert response.status_code == 403, f"{method} {path}: {response.text}"


def test_unauthenticated_gets_401_on_admin_endpoints(anon_client):
    for path in ("/api/admin/stats", "/api/admin/users"):
        response = anon_client.get(path)
        assert response.status_code == 401, f"{path}: {response.text}"


# --- users list / detail ------------------------------------------------------

def test_admin_lists_users_with_counts(db, anon_client):
    admin = _make_admin(anon_client, db)
    user_a = register_user(anon_client, email="a@example.com", password=PASSWORD)
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    monitor_a1 = _make_monitor_row(db, user_a["id"], name="A one")
    # A's second monitor has no alerts: it counts as a monitor, not an alert.
    _make_monitor_row(db, user_a["id"], name="A two")
    monitor_b = _make_monitor_row(db, user_b["id"], name="B one")
    _seed_alert(db, monitor_a1.id)
    _seed_alert(db, monitor_a1.id)
    _seed_alert(db, monitor_b.id)

    response = anon_client.get("/api/admin/users", headers=admin["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    by_email = {item["email"]: item for item in body["items"]}

    assert by_email[ADMIN_EMAIL]["is_admin"] is True
    assert by_email[ADMIN_EMAIL]["monitor_count"] == 0
    assert by_email[ADMIN_EMAIL]["alert_count"] == 0

    assert by_email["a@example.com"]["is_admin"] is False
    assert by_email["a@example.com"]["is_active"] is True
    assert by_email["a@example.com"]["monitor_count"] == 2
    assert by_email["a@example.com"]["alert_count"] == 2

    assert by_email["b@example.com"]["monitor_count"] == 1
    assert by_email["b@example.com"]["alert_count"] == 1


def test_admin_user_detail(db, anon_client):
    admin = _make_admin(anon_client, db)
    user = register_user(anon_client, email="detail@example.com", password=PASSWORD)
    monitor = _make_monitor_row(db, user["id"])
    _seed_alert(db, monitor.id)

    response = anon_client.get(
        f"/api/admin/users/{user['id']}", headers=admin["headers"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == user["id"]
    assert body["email"] == "detail@example.com"
    assert body["is_active"] is True
    assert body["is_admin"] is False
    assert body["monitor_count"] == 1
    assert body["alert_count"] == 1


def test_admin_user_detail_unknown_user_404(db, anon_client):
    admin = _make_admin(anon_client, db)
    response = anon_client.get("/api/admin/users/999999", headers=admin["headers"])
    assert response.status_code == 404


# --- deactivate / reactivate --------------------------------------------------

def test_admin_deactivate_blocks_login_and_token_then_reactivate(
    db, anon_client
):
    admin = _make_admin(anon_client, db)
    user = register_user(anon_client, email="victim@example.com", password=PASSWORD)
    old_headers = user["headers"]
    assert anon_client.get("/api/auth/me", headers=old_headers).status_code == 200

    response = anon_client.patch(
        f"/api/admin/users/{user['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False

    # Login fails, and the pre-deactivation token is rejected too.
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": PASSWORD},
        ).status_code
        == 401
    )
    assert anon_client.get("/api/auth/me", headers=old_headers).status_code == 401

    # Reactivate: login works again.
    response = anon_client.patch(
        f"/api/admin/users/{user['id']}",
        json={"is_active": True},
        headers=admin["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is True
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "victim@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )


def test_admin_cannot_deactivate_self_or_other_admin(db, anon_client):
    admin = _make_admin(anon_client, db)
    other_admin = _make_admin(anon_client, db, email="admin2@example.com")

    response = anon_client.patch(
        f"/api/admin/users/{admin['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert response.status_code == 400, response.text

    response = anon_client.patch(
        f"/api/admin/users/{other_admin['id']}",
        json={"is_active": False},
        headers=admin["headers"],
    )
    assert response.status_code == 400, response.text

    # Both admins are still active — and the caller's session still works.
    db.expire_all()
    assert db.get(User, admin["id"]).is_active is True
    assert db.get(User, other_admin["id"]).is_active is True
    assert (
        anon_client.get("/api/admin/stats", headers=admin["headers"]).status_code
        == 200
    )


# --- delete -------------------------------------------------------------------

def test_admin_delete_cascades_to_monitors_alerts_records(db, anon_client):
    admin = _make_admin(anon_client, db)
    victim = register_user(anon_client, email="gone@example.com", password=PASSWORD)
    survivor = register_user(anon_client, email="stays@example.com", password=PASSWORD)

    monitor = _make_monitor_row(db, victim["id"], name="Victim API")
    _seed_alert(db, monitor.id)
    _seed_record(db, monitor.id)
    survivor_monitor = _make_monitor_row(db, survivor["id"], name="Survivor API")
    _seed_alert(db, survivor_monitor.id)
    # Capture plain ints BEFORE the delete: after expire_all(), touching
    # an attribute of the deleted Monitor instance raises
    # ObjectDeletedError instead of returning the id.
    monitor_id = monitor.id
    survivor_monitor_id = survivor_monitor.id

    response = anon_client.delete(
        f"/api/admin/users/{victim['id']}", headers=admin["headers"]
    )
    assert response.status_code == 204, response.text

    db.expire_all()
    assert db.get(User, victim["id"]) is None
    assert (
        db.query(Monitor).filter(Monitor.user_id == victim["id"]).count() == 0
    )
    assert db.get(Monitor, monitor_id) is None
    assert db.query(Alert).filter(Alert.monitor_id == monitor_id).count() == 0
    assert (
        db.query(MonitoringRecord)
        .filter(MonitoringRecord.monitor_id == monitor_id)
        .count()
        == 0
    )

    # The other user's data is untouched.
    assert db.get(User, survivor["id"]) is not None
    assert db.get(Monitor, survivor_monitor_id) is not None
    assert (
        db.query(Alert)
        .filter(Alert.monitor_id == survivor_monitor_id)
        .count()
        == 1
    )


def test_admin_cannot_delete_self_or_other_admin(db, anon_client):
    admin = _make_admin(anon_client, db)
    other_admin = _make_admin(anon_client, db, email="admin2@example.com")

    response = anon_client.delete(
        f"/api/admin/users/{admin['id']}", headers=admin["headers"]
    )
    assert response.status_code == 400, response.text

    response = anon_client.delete(
        f"/api/admin/users/{other_admin['id']}", headers=admin["headers"]
    )
    assert response.status_code == 400, response.text

    db.expire_all()
    assert db.get(User, admin["id"]) is not None
    assert db.get(User, other_admin["id"]) is not None
    assert db.query(User).count() == 2


# --- stats ----------------------------------------------------------------------

def test_admin_stats_counts(db, anon_client):
    admin = _make_admin(anon_client, db)
    user_a = register_user(anon_client, email="a@example.com", password=PASSWORD)
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    monitor_a1 = _make_monitor_row(db, user_a["id"], name="A one")
    _make_monitor_row(db, user_a["id"], name="A two")
    monitor_b = _make_monitor_row(db, user_b["id"], name="B one")
    _seed_alert(db, monitor_a1.id)
    _seed_alert(db, monitor_a1.id)
    _seed_alert(db, monitor_b.id)

    response = anon_client.get("/api/admin/stats", headers=admin["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_users"] == 3
    assert body["total_monitors"] == 3
    assert body["total_alerts"] == 3


# --- monitors list --------------------------------------------------------------

def test_admin_monitors_list_shows_owner_and_filters(db, anon_client):
    admin = _make_admin(anon_client, db)
    user_a = register_user(anon_client, email="a@example.com", password=PASSWORD)
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    _make_monitor_row(db, user_a["id"], name="A one")
    _make_monitor_row(db, user_a["id"], name="A two")
    _make_monitor_row(db, user_b["id"], name="B one")

    response = anon_client.get("/api/admin/monitors", headers=admin["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    by_name = {item["name"]: item for item in body["items"]}
    assert by_name["A one"]["owner_email"] == "a@example.com"
    assert by_name["A two"]["owner_email"] == "a@example.com"
    assert by_name["B one"]["owner_email"] == "b@example.com"
    assert by_name["A one"]["user_id"] == user_a["id"]

    filtered = anon_client.get(
        f"/api/admin/monitors?user_id={user_a['id']}", headers=admin["headers"]
    )
    assert filtered.status_code == 200, filtered.text
    filtered_body = filtered.json()
    assert filtered_body["total"] == 2
    assert {item["name"] for item in filtered_body["items"]} == {"A one", "A two"}
    assert all(
        item["owner_email"] == "a@example.com"
        for item in filtered_body["items"]
    )


# --- /me ------------------------------------------------------------------------

def test_me_includes_is_admin(db, anon_client):
    admin = _make_admin(anon_client, db)
    user = register_user(anon_client, email="normal@example.com", password=PASSWORD)

    admin_me = anon_client.get("/api/auth/me", headers=admin["headers"])
    assert admin_me.status_code == 200
    assert admin_me.json()["is_admin"] is True

    user_me = anon_client.get("/api/auth/me", headers=user["headers"])
    assert user_me.status_code == 200
    assert user_me.json()["is_admin"] is False
