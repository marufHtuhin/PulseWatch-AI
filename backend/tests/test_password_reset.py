"""Forgot/reset password (v4.1): email OTP flow via Brevo.

The Brevo send is ALWAYS mocked in these tests (``mocked_send`` fixture)
— no test ever touches the real Brevo API. The plain OTP is captured
from the mocked call's arguments, exactly as a user would read it from
their inbox. One test deliberately runs WITHOUT the mock to prove the
endpoint does not crash when Brevo is unconfigured (the service returns
False before any network call in that case).
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from unittest.mock import Mock

import pytest

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.utils.time import to_naive_utc, utcnow
from tests.conftest import register_user, wait_for_next_second

PASSWORD = "correct-horse-123"
NEW_PASSWORD = "brand-new-horse-456"
FORGOT_GENERIC = "If an account exists for this email, a reset code has been sent."
RESET_INVALID = "Invalid or expired reset code."
RESET_SUCCESS = "Password reset successfully. You can now sign in with your new password."

# Mock path confirmed by the backend worker: auth.py does
# ``from app.services import email_service`` and calls
# ``email_service.send_password_reset_email(...)``.
_SEND_PATH = "app.api.routes.auth.email_service.send_password_reset_email"


@pytest.fixture()
def mocked_send(monkeypatch):
    """Mock the Brevo send; return the Mock so tests can read the OTP
    from its call arguments: ``mock.call_args[0] == (email, otp)``."""
    mock = Mock(return_value=True)
    monkeypatch.setattr(_SEND_PATH, mock)
    return mock


def _tokens_for(db, user_id: int) -> list[PasswordResetToken]:
    """All reset-token rows for a user, oldest first."""
    db.expire_all()
    return (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user_id)
        .order_by(PasswordResetToken.id.asc())
        .all()
    )


def _forgot(anon_client, email: str):
    return anon_client.post("/api/auth/forgot-password", json={"email": email})


def _reset(anon_client, email: str, otp: str, new_password: str = NEW_PASSWORD):
    return anon_client.post(
        "/api/auth/reset-password",
        json={"email": email, "otp": otp, "new_password": new_password},
    )


def _wrong_otp(real_otp: str) -> str:
    """A 6-digit code guaranteed to differ from the real one."""
    return "000000" if real_otp != "000000" else "111111"


# --- forgot-password ---------------------------------------------------------

def test_forgot_password_existing_user_sends_code_and_stores_hash(
    anon_client, db, mocked_send
):
    user = register_user(anon_client, email="reset@example.com", password=PASSWORD)

    response = _forgot(anon_client, "reset@example.com")

    assert response.status_code == 200
    assert response.json()["message"] == FORGOT_GENERIC
    # Exactly one send, to the right address, with a 6-digit code.
    mocked_send.assert_called_once()
    sent_email, otp = mocked_send.call_args[0]
    assert sent_email == "reset@example.com"
    assert len(otp) == 6 and otp.isdigit()

    # One token row; the OTP itself is NEVER stored — only its sha256 hex.
    tokens = _tokens_for(db, user["id"])
    assert len(tokens) == 1
    token = tokens[0]
    assert token.otp_hash == hashlib.sha256(otp.encode()).hexdigest()
    assert len(token.otp_hash) == 64
    assert otp not in token.otp_hash
    assert token.used is False
    assert token.attempts == 0
    # 10-minute expiry: in the future, and not absurdly far out.
    now = to_naive_utc(utcnow())
    assert now < token.expires_at <= now + timedelta(minutes=11)


def test_forgot_password_unknown_email_returns_generic_without_sending(
    anon_client, db, mocked_send
):
    # No user exists for this address at all.
    response = _forgot(anon_client, "nobody@example.com")

    # The SAME generic 200 as for a real user: no enumeration leak.
    assert response.status_code == 200
    assert response.json()["message"] == FORGOT_GENERIC
    mocked_send.assert_not_called()
    assert db.query(PasswordResetToken).count() == 0


def test_forgot_password_unconfigured_email_still_returns_200(
    anon_client, db, monkeypatch
):
    """Brevo not configured (the default in tests): the endpoint must
    still return the generic 200 and still create the token row — the
    service returns False without raising, and the code path must not
    crash. Runs WITHOUT the send mock on purpose."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "BREVO_API_KEY", None)
    monkeypatch.setattr(settings, "EMAIL_FROM", None)
    user = register_user(anon_client, email="unconfigured@example.com", password=PASSWORD)

    # No exception, no network call (the service short-circuits on the
    # missing config before creating an httpx client).
    response = _forgot(anon_client, "unconfigured@example.com")

    assert response.status_code == 200
    assert response.json()["message"] == FORGOT_GENERIC
    tokens = _tokens_for(db, user["id"])
    assert len(tokens) == 1
    assert tokens[0].used is False


def test_forgot_password_per_email_cap_is_three_per_hour(
    anon_client, db, mocked_send
):
    user = register_user(anon_client, email="capped@example.com", password=PASSWORD)

    for _ in range(3):
        response = _forgot(anon_client, "capped@example.com")
        assert response.status_code == 200
        assert response.json()["message"] == FORGOT_GENERIC

    tokens = _tokens_for(db, user["id"])
    assert len(tokens) == 3
    assert mocked_send.call_count == 3
    # Each new request invalidates the previous unused code: only the
    # latest one is live.
    assert [t.used for t in tokens] == [True, True, False]

    # A 4th request in the hour: still the generic 200, but nothing is
    # created and nothing is sent.
    response = _forgot(anon_client, "capped@example.com")
    assert response.status_code == 200
    assert response.json()["message"] == FORGOT_GENERIC
    assert len(_tokens_for(db, user["id"])) == 3
    assert mocked_send.call_count == 3


# --- reset-password ----------------------------------------------------------

def test_reset_password_correct_otp_resets_and_invalidates_old_session(
    anon_client, db, mocked_send
):
    user = register_user(anon_client, email="good-reset@example.com", password=PASSWORD)
    old_headers = user["headers"]
    # The old token must predate the reset by a whole second, or the
    # second-precision iat check cannot tell them apart.
    wait_for_next_second()
    assert _forgot(anon_client, "good-reset@example.com").status_code == 200
    otp = mocked_send.call_args[0][1]

    response = _reset(anon_client, "good-reset@example.com", otp)

    assert response.status_code == 200
    assert response.json()["message"] == RESET_SUCCESS
    # The code is single-use: its row is marked used.
    tokens = _tokens_for(db, user["id"])
    assert len(tokens) == 1
    assert tokens[0].used is True

    # New password works, old password does not.
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "good-reset@example.com", "password": NEW_PASSWORD},
        ).status_code
        == 200
    )
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "good-reset@example.com", "password": PASSWORD},
        ).status_code
        == 401
    )
    # The session from before the reset is dead.
    assert anon_client.get("/api/auth/me", headers=old_headers).status_code == 401


def test_reset_password_wrong_otp_is_400_and_increments_attempts(
    anon_client, db, mocked_send
):
    user = register_user(anon_client, email="wrong-otp@example.com", password=PASSWORD)
    assert _forgot(anon_client, "wrong-otp@example.com").status_code == 200
    otp = mocked_send.call_args[0][1]

    response = _reset(anon_client, "wrong-otp@example.com", _wrong_otp(otp))

    assert response.status_code == 400
    assert response.json()["detail"] == RESET_INVALID
    tokens = _tokens_for(db, user["id"])
    assert len(tokens) == 1
    assert tokens[0].attempts == 1
    assert tokens[0].used is False
    # The password is untouched: the old password still logs in.
    assert (
        anon_client.post(
            "/api/auth/login",
            json={"email": "wrong-otp@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )


def test_reset_password_expired_otp_is_400(anon_client, db, mocked_send):
    user = register_user(anon_client, email="expired-otp@example.com", password=PASSWORD)
    assert _forgot(anon_client, "expired-otp@example.com").status_code == 200
    otp = mocked_send.call_args[0][1]
    # Age the token past its 10-minute TTL.
    token = _tokens_for(db, user["id"])[0]
    token.expires_at = to_naive_utc(utcnow()) - timedelta(minutes=1)
    db.commit()

    response = _reset(anon_client, "expired-otp@example.com", otp)

    assert response.status_code == 400
    assert response.json()["detail"] == RESET_INVALID


def test_reset_password_locks_after_five_wrong_attempts(
    anon_client, db, mocked_send
):
    user = register_user(anon_client, email="locked@example.com", password=PASSWORD)
    assert _forgot(anon_client, "locked@example.com").status_code == 200
    otp = mocked_send.call_args[0][1]
    wrong = _wrong_otp(otp)

    for _ in range(5):
        response = _reset(anon_client, "locked@example.com", wrong)
        assert response.status_code == 400
        assert response.json()["detail"] == RESET_INVALID

    tokens = _tokens_for(db, user["id"])
    assert tokens[0].attempts == 5
    assert tokens[0].used is True  # locked

    # Even the CORRECT code no longer works once the token is locked.
    response = _reset(anon_client, "locked@example.com", otp)
    assert response.status_code == 400
    assert response.json()["detail"] == RESET_INVALID


def test_reset_password_reused_otp_is_400(anon_client, db, mocked_send):
    register_user(anon_client, email="reuse@example.com", password=PASSWORD)
    assert _forgot(anon_client, "reuse@example.com").status_code == 200
    otp = mocked_send.call_args[0][1]

    first = _reset(anon_client, "reuse@example.com", otp)
    assert first.status_code == 200

    # The same code a second time: single-use means 400.
    second = _reset(anon_client, "reuse@example.com", otp)
    assert second.status_code == 400
    assert second.json()["detail"] == RESET_INVALID


def test_reset_password_unknown_email_is_400_generic(anon_client, mocked_send):
    # No user, no token — the same generic 400 as every other failure,
    # so the endpoint cannot enumerate users.
    response = _reset(anon_client, "nobody@example.com", "123456")
    assert response.status_code == 400
    assert response.json()["detail"] == RESET_INVALID
    mocked_send.assert_not_called()
