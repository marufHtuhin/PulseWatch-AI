"""Auth request/response schemas (POST /api/auth/*)."""
from __future__ import annotations

from pydantic import EmailStr, Field

from app.schemas.common import APIModel, UtcDateTime


class UserOut(APIModel):
    id: int
    email: str
    # The frontend shows the Admin nav link only when this is true.
    is_admin: bool = False
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


class ChangePasswordRequest(APIModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordResponse(APIModel):
    """POST /api/auth/change-password response (200): a fresh token, so
    the session that changed the password survives while all older
    tokens die via the ``password_changed_at`` check."""

    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(APIModel):
    email: EmailStr


class ForgotPasswordResponse(APIModel):
    """POST /api/auth/forgot-password response (200). Always the same
    generic message — never reveals whether the email exists."""

    message: str


class ResetPasswordRequest(APIModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


class ResetPasswordResponse(APIModel):
    """POST /api/auth/reset-password response (200)."""

    message: str
