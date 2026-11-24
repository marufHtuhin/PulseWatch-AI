"""Password reset token model: one row per forgot-password request.

Only the sha256 hex digest of the 6-digit OTP is stored, never the OTP
itself. A token is single-use (``used``) and short-lived (10 minutes);
``attempts`` caps wrong guesses at 5, after which the row is marked used
(locked). Requesting a new code marks the user's previous unused tokens
used, so at most one live code exists per user.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.time import utcnow


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ON DELETE CASCADE: deleting a user removes their reset tokens.
    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_password_reset_tokens_user_id",
        ),
        nullable=False,
        index=True,
    )
    # sha256 hex digest of the 6-digit OTP — the OTP itself is never stored.
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Wrong-guess counter; >= 5 locks the token (marked used).
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Consumed, superseded by a newer code, or locked after too many attempts.
    used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now()
    )
