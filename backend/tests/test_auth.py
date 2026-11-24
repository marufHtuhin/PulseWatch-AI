"""Auth (v4): registration, login, JWT protection, per-user isolation,
and the admin bootstrap that claims pre-v4 ownerless data.

``client`` is auto-authenticated as user A (the fixture's test user);
user B is registered on demand via ``register_user(anon_client)`` and
talks through ``anon_client`` with B's own Authorization headers.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.auth import bootstrap_admin, create_access_token
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.monitor import Monitor
from app.models.settings import AppSettings
from app.models.user import User
from app.services.monitoring_service import run_check
from app.services.settings_service import get_or_create_settings
from tests.conftest import (
    json_response_handler,
    mock_client_factory,
    monitor_payload,
    register_user,
    wait_for_next_second,
)

PASSWORD = "correct-horse-123"
NEW_PASSWORD = "brand-new-horse-456"


# --- registration -----------------------------------------------------------

def test_register_success_returns_201_with_user_and_working_token(anon_client):
    response = anon_client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": PASSWORD},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert isinstance(body["user"]["id"], int)
    assert body["user"]["created_at"]
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    # No password material ever leaks into a response.
    assert "password_hash" not in response.text
    assert PASSWORD not in response.text

    # The token from registration works immediately.
    me = anon_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]
    assert me.json()["email"] == "alice@example.com"


def test_register_duplicate_email_is_400(anon_client):
    register_user(anon_client, email="dup@example.com", password=PASSWORD)
    response = anon_client.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "password": PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_register_short_password_is_422(anon_client):
    response = anon_client.post(
        "/api/auth/register",
        json={"email": "short@example.com", "password": "short7!"},
    )
    assert response.status_code == 422


def test_register_invalid_email_is_422(anon_client):
    response = anon_client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": PASSWORD},
    )
    assert response.status_code == 422


# --- login ------------------------------------------------------------------

def test_login_success_returns_token_that_works_for_me(anon_client):
    register_user(anon_client, email="bob@example.com", password=PASSWORD)
    response = anon_client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = anon_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.com"


def test_login_wrong_password_is_401(anon_client):
    register_user(anon_client, email="carol@example.com", password=PASSWORD)
    response = anon_client.post(
        "/api/auth/login",
        json={"email": "carol@example.com", "password": "wrong-password-1"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_unknown_user_is_401(anon_client):
    # Same message as a wrong password: the endpoint must not reveal
    # whether the email exists.
    response = anon_client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


# --- /me and token validation -----------------------------------------------

def test_me_without_token_is_401(anon_client):
    response = anon_client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_me_with_invalid_token_is_401(anon_client):
    response = anon_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer this-is-not-a-token"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_me_with_expired_token_is_401(anon_client):
    user = register_user(anon_client, email="expired@example.com", password=PASSWORD)
    expired = create_access_token(user["id"], expires_delta=timedelta(seconds=-1))
    response = anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_me_with_deactivated_user_is_401(anon_client, db):
    user = register_user(anon_client, email="gone@example.com", password=PASSWORD)
    db.query(User).filter(User.id == user["id"]).update(
        {User.is_active: False}, synchronize_session=False
    )
    db.commit()

    response = anon_client.get("/api/auth/me", headers=user["headers"])
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


# --- protected vs public endpoints ------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/api/monitors",
        "/api/alerts",
        "/api/alerts/history",
        "/api/dashboard/summary",
        "/api/dashboard/health",
        "/api/settings",
        "/api/monitoring/history",
        "/api/auth/me",
    ],
)
def test_protected_endpoints_require_auth(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_protected_post_requires_auth(anon_client):
    response = anon_client.post("/api/monitors", json=monitor_payload())
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.parametrize("path", ["/", "/health", "/docs"])
def test_public_endpoints_stay_public(anon_client, path):
    assert anon_client.get(path).status_code == 200


# --- cross-user isolation ---------------------------------------------------

def test_cross_user_monitor_access_is_404(client, anon_client, create_monitor_via_api):
    monitor = create_monitor_via_api(name="A's monitor")
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    assert client.get(f"/api/monitors/{monitor['id']}").status_code == 200
    assert (
        anon_client.get(
            f"/api/monitors/{monitor['id']}", headers=user_b["headers"]
        ).status_code
        == 404
    )
    assert (
        anon_client.put(
            f"/api/monitors/{monitor['id']}",
            json=monitor_payload(name="hijacked"),
            headers=user_b["headers"],
        ).status_code
        == 404
    )
    assert (
        anon_client.delete(
            f"/api/monitors/{monitor['id']}", headers=user_b["headers"]
        ).status_code
        == 404
    )
    # B's attempts changed nothing: A still owns the monitor.
    assert client.get(f"/api/monitors/{monitor['id']}").status_code == 200


def test_cross_user_monitor_list_excludes_others(
    client, anon_client, create_monitor_via_api
):
    create_monitor_via_api(name="A's monitor")
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    mine = client.get("/api/monitors").json()
    assert mine["total"] == 1

    theirs = anon_client.get("/api/monitors", headers=user_b["headers"]).json()
    assert theirs["total"] == 0
    assert theirs["items"] == []


async def test_cross_user_alerts_excluded(client, anon_client, db, make_monitor):
    monitor = make_monitor(alert_after_failures=1, name="A's flaky API")
    factory = mock_client_factory(json_response_handler(status=500, payload={}))
    outcome = await run_check(db, monitor.id, client_factory=factory)
    assert len(outcome.alerts_created) == 1
    alert_id = outcome.alerts_created[0]  # alerts_created holds alert ids

    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    mine = client.get("/api/alerts").json()
    assert mine["total"] == 1

    theirs = anon_client.get("/api/alerts", headers=user_b["headers"]).json()
    assert theirs["total"] == 0
    assert theirs["items"] == []
    assert (
        anon_client.get(
            f"/api/alerts/{alert_id}", headers=user_b["headers"]
        ).status_code
        == 404
    )


def test_cross_user_batch_check_skips_foreign_monitors(
    client, anon_client, create_monitor_via_api
):
    monitor = create_monitor_via_api(name="A's monitor")
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    response = anon_client.post(
        "/api/monitoring/batch",
        json={"monitor_ids": [monitor["id"]]},
        headers=user_b["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    # Silently skipped: the foreign id simply does not appear.
    assert body["results"] == []
    assert body["succeeded"] == 0
    assert body["failed"] == 0


def test_settings_isolated_per_user(client, anon_client):
    user_b = register_user(anon_client, email="b@example.com", password=PASSWORD)

    put = client.put("/api/settings", json={"retention_days": 30})
    assert put.status_code == 200
    assert put.json()["retention_days"] == 30

    # B still sees the defaults — A's settings are not theirs.
    theirs = anon_client.get("/api/settings", headers=user_b["headers"])
    assert theirs.status_code == 200
    assert theirs.json()["retention_days"] == 90

    # And B's own change does not leak back to A.
    anon_client.put(
        "/api/settings", json={"retention_days": 60}, headers=user_b["headers"]
    )
    assert client.get("/api/settings").json()["retention_days"] == 30


# --- admin bootstrap --------------------------------------------------------

def test_admin_bootstrap_claims_ownerless_monitors_and_settings(
    db, make_monitor, monkeypatch
):
    orphan = make_monitor(user_id=None, name="Orphan API")
    ownerless_row = get_or_create_settings(db)  # the pre-v4 settings row
    # Bootstrap is skipped while TESTING; the test opts back in.
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "admin-password-123")

    bootstrap_admin(db)
    db.expire_all()

    admin = db.query(User).filter(User.email == "admin@example.com").first()
    assert admin is not None
    assert db.get(Monitor, orphan.id).user_id == admin.id
    assert db.get(AppSettings, ownerless_row.id).user_id == admin.id

    # Idempotent: a second run creates no second admin user.
    bootstrap_admin(db)
    assert (
        db.query(User).filter(User.email == "admin@example.com").count() == 1
    )


def test_admin_bootstrap_does_nothing_without_admin_env(
    db, make_monitor, monkeypatch
):
    orphan = make_monitor(user_id=None, name="Orphan API")
    monkeypatch.setattr(settings, "TESTING", False)
    # ADMIN_EMAIL / ADMIN_PASSWORD stay unset (None by default).

    bootstrap_admin(db)
    db.expire_all()

    assert db.get(Monitor, orphan.id).user_id is None
    # Only the fixture's test user exists — no admin was created.
    assert db.query(User).count() == 1


# --- change-password (v4.1) -------------------------------------------------

def test_change_password_success_returns_fresh_token_and_kills_old_sessions(
    anon_client,
):
    user = register_user(anon_client, email="changer@example.com", password=PASSWORD)
    old_headers = user["headers"]
    # The old token must predate the change by a whole second, or the
    # second-precision iat check cannot tell them apart.
    wait_for_next_second()

    response = anon_client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=old_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["access_token"] != user["token"]

    # The fresh token works immediately; the old one is dead.
    fresh_headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = anon_client.get("/api/auth/me", headers=fresh_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "changer@example.com"
    assert anon_client.get("/api/auth/me", headers=old_headers).status_code == 401

    # Login confirms the password actually changed.
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "changer@example.com", "password": NEW_PASSWORD},
        ).status_code
        == 200
    )
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "changer@example.com", "password": PASSWORD},
        ).status_code
        == 401
    )


def test_change_password_wrong_current_is_401_and_keeps_session(anon_client):
    user = register_user(anon_client, email="wrong-current@example.com", password=PASSWORD)

    response = anon_client.post(
        "/api/auth/change-password",
        json={"current_password": "not-my-password-1", "new_password": NEW_PASSWORD},
        headers=user["headers"],
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Current password is incorrect"

    # A failed attempt kills nothing: the session still works and the
    # old password still logs in.
    assert anon_client.get("/api/auth/me", headers=user["headers"]).status_code == 200
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "wrong-current@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )


def test_change_password_requires_auth(anon_client):
    response = anon_client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


# --- rate limiting (v4.1) ---------------------------------------------------

def test_login_rate_limit_returns_429_after_five_attempts(anon_client):
    """The limiter is disabled under TESTING by default; this test flips
    it on, proves the 6th login in a minute is a JSON 429, and flips it
    back off — the rest of the suite must never be rate-limited."""
    register_user(anon_client, email="limited@example.com", password=PASSWORD)
    # A unique X-Forwarded-For IP: the key function prefers XFF, so this
    # test's bucket cannot collide with any other test's.
    headers = {"X-Forwarded-For": "203.0.113.99"}
    assert limiter.enabled is False  # disabled under TESTING

    limiter.enabled = True
    try:
        for _ in range(5):
            response = anon_client.post(
                "/api/auth/login",
                json={"email": "limited@example.com", "password": PASSWORD},
                headers=headers,
            )
            assert response.status_code == 200
        sixth = anon_client.post(
            "/api/auth/login",
            json={"email": "limited@example.com", "password": PASSWORD},
            headers=headers,
        )
        assert sixth.status_code == 429
        assert "detail" in sixth.json()
    finally:
        limiter.enabled = False

    assert limiter.enabled is False
    # And logins work again immediately once the limiter is off.
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "limited@example.com", "password": PASSWORD},
            headers=headers,
        ).status_code
        == 200
    )
