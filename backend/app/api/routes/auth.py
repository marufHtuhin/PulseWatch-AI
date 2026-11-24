"""Auth endpoints: open registration, login, current user, password
change, and forgot/reset password (email OTP).

These are the only /api/* routes that do NOT require authentication
(except /change-password, which needs a valid session).
Registration is open (anyone can create an account); each account sees
only its own monitors, alerts, records, dashboard data, and settings.

Rate limits (slowapi, disabled when TESTING — see app.core.rate_limit):
login 5/minute, register 10/hour, forgot-password 5/hour,
reset-password 10/hour. /me and /change-password are not rate-limited:
change-password is authed, so wrong-current-password attempts are
already gated by needing a valid session.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.database.connection import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    UserOut,
)
from app.services import email_service
from app.utils.time import to_naive_utc, utcnow

logger = get_logger("api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every login failure (unknown user, wrong password,
# deactivated account) so the endpoint cannot be used to enumerate users.
_INVALID_CREDENTIALS = "Invalid email or password"
# Generic forgot-password reply: never reveals whether the email exists.
_FORGOT_GENERIC = "If an account exists for this email, a reset code has been sent."
# Generic reset-password failure: never says which check failed (no user,
# no token, expired, used, or wrong code).
_RESET_INVALID = "Invalid or expired reset code."
_RESET_SUCCESS = "Password reset successfully. You can now sign in with your new password."

RESET_CODE_TTL = timedelta(minutes=10)
# Abuse caps: at most 3 codes per email per hour; at most 5 wrong guesses
# per code before it locks.
FORGOT_REQUESTS_PER_HOUR = 3
RESET_MAX_ATTEMPTS = 5


def _hash_otp(otp: str) -> str:
    """sha256 hex digest — the OTP itself is never stored."""
    return hashlib.sha256(otp.encode()).hexdigest()


def _invalidate_unused_tokens(db: Session, user_id: int) -> None:
    """Mark the user's unused reset tokens used (superseded / consumed)."""
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used.is_(False),
    ).update({PasswordResetToken.used: True}, synchronize_session=False)


@router.post("/register", response_model=AuthResponse, status_code=201)
@limiter.limit("10/hour")
def register(
    request: Request, payload: RegisterRequest, db: Session = Depends(get_db)
) -> AuthResponse:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("user registered id=%s email=%s", user.id, user.email)
    return AuthResponse(
        user=UserOut.model_validate(user),
        access_token=create_access_token(user.id),
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(
    request: Request, payload: LoginRequest, db: Session = Depends(get_db)
) -> LoginResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)
    return LoginResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangePasswordResponse:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    # Kills every other session: tokens issued before this instant are
    # rejected by get_current_user's iat check. Truncated to whole
    # seconds — the JWT iat claim is second-precision, so a
    # microsecond-precise timestamp would reject even the fresh token
    # issued below in the same second.
    current_user.password_changed_at = utcnow().replace(microsecond=0)
    db.commit()
    logger.info("password changed user_id=%s", current_user.id)
    # Fresh token so THIS session survives the change.
    return ChangePasswordResponse(access_token=create_access_token(current_user.id))


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
@limiter.limit("5/hour")
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    # ALWAYS the generic 200 — never reveal whether the email exists.
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None:
        return ForgotPasswordResponse(message=_FORGOT_GENERIC)
    # Per-email abuse cap: at most 3 codes per hour. Over the cap, return
    # the generic 200 WITHOUT creating or sending anything.
    one_hour_ago = to_naive_utc(utcnow()) - timedelta(hours=1)
    recent = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at >= one_hour_ago,
        )
        .count()
    )
    if recent >= FORGOT_REQUESTS_PER_HOUR:
        logger.info(
            "forgot-password rate cap hit user_id=%s (no code sent)", user.id
        )
        return ForgotPasswordResponse(message=_FORGOT_GENERIC)
    _invalidate_unused_tokens(db, user.id)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    token = PasswordResetToken(
        user_id=user.id,
        otp_hash=_hash_otp(otp),
        expires_at=to_naive_utc(utcnow()) + RESET_CODE_TTL,
    )
    db.add(token)
    db.commit()
    # If Brevo is not configured the service logs a warning and returns
    # False — the endpoint still returns the generic 200. The OTP is
    # never logged.
    email_service.send_password_reset_email(payload.email, otp)
    return ForgotPasswordResponse(message=_FORGOT_GENERIC)


@router.post("/reset-password", response_model=ResetPasswordResponse)
@limiter.limit("10/hour")
def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> ResetPasswordResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    token = None
    if user is not None:
        token = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used.is_(False),
            )
            .order_by(PasswordResetToken.created_at.desc())
            .first()
        )
    now = to_naive_utc(utcnow())
    if token is None or token.expires_at < now:
        # No user, no live token, or expired — same generic 400 for all.
        raise HTTPException(status_code=400, detail=_RESET_INVALID)
    if not hmac.compare_digest(_hash_otp(payload.otp), token.otp_hash):
        token.attempts += 1
        if token.attempts >= RESET_MAX_ATTEMPTS:
            # Lock the token after too many wrong guesses.
            token.used = True
        db.commit()
        raise HTTPException(status_code=400, detail=_RESET_INVALID)
    user.password_hash = hash_password(payload.new_password)
    # Kills every other session (see change-password). Whole seconds,
    # for the same iat-precision reason as there.
    user.password_changed_at = utcnow().replace(microsecond=0)
    token.used = True
    _invalidate_unused_tokens(db, user.id)
    db.commit()
    logger.info("password reset user_id=%s", user.id)
    return ResetPasswordResponse(message=_RESET_SUCCESS)
