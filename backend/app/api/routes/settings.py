"""Settings endpoints (single-row persisted defaults)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.core.logging import get_logger
from app.database.connection import get_db
from app.models.settings import AppSettings
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.settings_service import get_or_create_settings

logger = get_logger("api.settings")

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_response(row: AppSettings) -> SettingsOut:
    return SettingsOut(
        default_interval_seconds=row.default_interval_seconds,
        default_timeout_seconds=row.default_timeout_seconds,
        default_latency_threshold_ms=row.default_latency_threshold_ms,
        max_concurrency=row.max_concurrency,
        gemini_configured=bool(app_settings.GEMINI_API_KEY),
        allow_local_urls=app_settings.ALLOW_LOCAL_URLS,
        app_env=app_settings.APP_ENV,
    )


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)) -> SettingsOut:
    return _to_response(get_or_create_settings(db))


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    row = get_or_create_settings(db)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field_name, value)
    db.commit()
    db.refresh(row)
    logger.info("settings updated")
    return _to_response(row)
