"""Authentication: bcrypt passwords + JWT (HS256) access tokens.

- Passwords are hashed with passlib's bcrypt CryptContext; plaintext
  passwords are never stored or logged.
- Access tokens carry ``sub`` = the user id (as a string) and expire after
  24 hours. They are validated by the ``get_current_user`` FastAPI
  dependency, which every ``/api/*`` route except ``/api/auth/*`` requires.
- ``bootstrap_admin`` claims pre-v4 ownerless data for the admin user at
  startup (see main.py's lifespan hook).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.database.connection import get_db
from app.models.monitor import Monitor
from app.models.settings import AppSettings
from app.models.user import User

logger = get_logger("auth")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# auto_error=False: a missing token must be a 401 ("Authentication
# required"), not HTTPBearer's default 403.
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    """Sign a JWT whose subject is the user id. 24h expiry by default."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    return jwt.encode({"sub": str(user_id), "exp": expire}, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """The user id from a valid token, or None when it is invalid/expired."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    subject = payload.get("sub")
    if subject is None:
        return None
    try:
        return int(subject)
    except (TypeError, ValueError):
        return None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: the authenticated user, or 401.

    401 when the token is missing, invalid, or expired, when the user no
    longer exists, or when the user is deactivated — all with the same
    generic message so no information leaks about which check failed.
    """
    if credentials is None:
        raise _unauthorized("Authentication required")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise _unauthorized("Could not validate credentials")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Could not validate credentials")
    return user


def bootstrap_admin(db: Session) -> None:
    """Create the admin user (if missing) and claim ownerless data for them.

    Runs once at startup when ADMIN_EMAIL and ADMIN_PASSWORD are both set
    (see main.py). Idempotent: re-running with the user already present
    just claims any ownerless rows that appeared since. Skipped entirely
    when TESTING, and never breaks startup — any failure (e.g. tables not
    migrated yet) is logged as a warning and swallowed.
    """
    if settings.TESTING:
        return
    email = settings.ADMIN_EMAIL
    password = settings.ADMIN_PASSWORD
    if not email or not password:
        return
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(email=email, password_hash=hash_password(password))
            db.add(user)
            db.flush()
            logger.info("admin bootstrap: created user email=%s", email)
        monitors_claimed = (
            db.query(Monitor)
            .filter(Monitor.user_id.is_(None))
            .update({Monitor.user_id: user.id}, synchronize_session=False)
        )
        # settings.user_id is unique, so claim at most one ownerless row
        # (in practice there is exactly one pre-v4 row, id 1); any extras
        # stay ownerless rather than breaking the bootstrap.
        ownerless_settings = (
            db.query(AppSettings)
            .filter(AppSettings.user_id.is_(None))
            .order_by(AppSettings.id.asc())
            .first()
        )
        settings_claimed = 0
        if ownerless_settings is not None:
            ownerless_settings.user_id = user.id
            settings_claimed = 1
        db.commit()
        if monitors_claimed or settings_claimed:
            logger.info(
                "admin bootstrap: claimed monitors=%s settings=%s for email=%s",
                monitors_claimed,
                settings_claimed,
                email,
            )
    except Exception:  # noqa: BLE001 - bootstrap must never break startup
        db.rollback()
        logger.warning(
            "admin bootstrap failed; startup continues without it",
            exc_info=True,
        )
