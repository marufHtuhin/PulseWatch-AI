"""Per-user settings helpers.

Each user has their own AppSettings row keyed by ``user_id`` (unique).
``user_id=None`` addresses the ownerless pre-v4 row — used only by the
scheduler/notification paths for ownerless monitors; API routes always
pass the current user's id.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.settings import AppSettings


def get_settings_row(db: Session, user_id: int | None = None) -> AppSettings | None:
    """The settings row for one user (``None`` = the ownerless row).

    Never creates a row — use ``get_or_create_settings`` for that.
    """
    query = db.query(AppSettings)
    if user_id is None:
        query = query.filter(AppSettings.user_id.is_(None))
    else:
        query = query.filter(AppSettings.user_id == user_id)
    return query.first()


def get_or_create_settings(db: Session, user_id: int | None = None) -> AppSettings:
    row = get_settings_row(db, user_id)
    if row is None:
        row = AppSettings(
            user_id=user_id,
            default_interval_seconds=300,
            default_timeout_seconds=10,
            default_latency_threshold_ms=3000,
            max_concurrency=settings.MAX_CONCURRENCY,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_effective_max_concurrency(db: Session, user_id: int | None = None) -> int:
    """Batch concurrency: the user's persisted setting wins, env config is
    the seed (and the fallback when the user has no settings row yet)."""
    row = get_settings_row(db, user_id)
    if row is not None:
        return row.max_concurrency
    return settings.MAX_CONCURRENCY
