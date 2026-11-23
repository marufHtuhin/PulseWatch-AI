"""Single-row settings helpers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.settings import AppSettings


def get_or_create_settings(db: Session) -> AppSettings:
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if row is None:
        row = AppSettings(
            id=1,
            default_interval_seconds=300,
            default_timeout_seconds=10,
            default_latency_threshold_ms=3000,
            max_concurrency=settings.MAX_CONCURRENCY,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_effective_max_concurrency(db: Session) -> int:
    """Batch concurrency: the persisted setting wins, env config is the seed."""
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if row is not None:
        return row.max_concurrency
    return settings.MAX_CONCURRENCY
