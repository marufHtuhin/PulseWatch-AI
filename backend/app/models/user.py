"""User model: one account in the multi-user (SaaS) deployment.

Users own monitors and a per-user settings row (``Monitor.user_id`` /
``AppSettings.user_id``). Authentication is JWT (HS256) — see
``app.core.auth``.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

if TYPE_CHECKING:
    from app.models.monitor import Monitor
    from app.models.settings import AppSettings


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # bcrypt hash (passlib CryptContext, schemes=["bcrypt"]) — never a
    # plaintext password, and never returned by any API response.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set whenever the password is changed or reset; JWTs issued before
    # this instant are rejected (see app.core.auth). NULL for users who
    # never changed their password — their pre-v4.1 tokens stay valid.
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, server_default=func.now()
    )

    monitors: Mapped[list["Monitor"]] = relationship(
        "Monitor", back_populates="owner", passive_deletes=True
    )
    settings_row: Mapped["AppSettings | None"] = relationship(
        "AppSettings", back_populates="owner", uselist=False, passive_deletes=True
    )
