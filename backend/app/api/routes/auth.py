"""Auth endpoints: open registration, login, current user.

These are the only /api/* routes that do NOT require authentication.
Registration is open (anyone can create an account); each account sees
only its own monitors, alerts, records, dashboard data, and settings.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.logging import get_logger
from app.database.connection import get_db
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserOut,
)

logger = get_logger("api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for every login failure (unknown user, wrong password,
# deactivated account) so the endpoint cannot be used to enumerate users.
_INVALID_CREDENTIALS = "Invalid email or password"


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
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
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
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
