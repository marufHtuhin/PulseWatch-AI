"""Auth request/response schemas (POST /api/auth/*)."""
from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas.common import APIModel, UtcDateTime


class UserOut(APIModel):
    id: int
    email: str
    created_at: UtcDateTime


class RegisterRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(APIModel):
    """POST /api/auth/register response (201)."""

    user: UserOut
    access_token: str
    token_type: str = "bearer"


class LoginResponse(APIModel):
    """POST /api/auth/login response (200)."""

    access_token: str
    token_type: str = "bearer"
