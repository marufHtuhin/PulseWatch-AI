"""Settings endpoints (one persisted row per user)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings as app_settings
from app.core.logging import get_logger
from app.core.security import MASKED_VALUE
from app.database.connection import get_db
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.settings import (
    CleanupResult,
    SettingsOut,
    SettingsUpdate,
    TestNotificationResult,
)
from app.services.notification_service import (
    resolve_telegram_credentials,
    send_test_notification,
)
from app.services.retention_service import preview_cleanup, run_cleanup
from app.services.settings_service import get_or_create_settings

logger = get_logger("api.settings")

router = APIRouter(prefix="/settings", tags=["settings"])


def _to_response(row: AppSettings) -> SettingsOut:
    token, chat_id = resolve_telegram_credentials(row)
    # ai_configured reflects the SELECTED provider only — a key for the
    # other provider does not count (mirrors ai_service's selection).
    ai_configured = (
        bool(app_settings.GEMINI_API_KEY)
        if app_settings.AI_PROVIDER == "gemini"
        else bool(app_settings.OPENROUTER_API_KEY)
    )
    return SettingsOut(
        default_interval_seconds=row.default_interval_seconds,
        default_timeout_seconds=row.default_timeout_seconds,
        default_latency_threshold_ms=row.default_latency_threshold_ms,
        max_concurrency=row.max_concurrency,
        ai_configured=ai_configured,
        ai_provider=app_settings.AI_PROVIDER,
        allow_local_urls=app_settings.ALLOW_LOCAL_URLS,
        app_env=app_settings.APP_ENV,
        telegram_enabled=row.telegram_enabled,
        telegram_min_severity=row.telegram_min_severity,
        # Configured = credentials available (DB or env). The token value
        # itself is never included in any response.
        telegram_configured=bool(token and chat_id),
        telegram_chat_id=chat_id or "",
        retention_days=row.retention_days,
        alert_retention_days=row.alert_retention_days,
    )


@router.get("", response_model=SettingsOut)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsOut:
    return _to_response(get_or_create_settings(db, current_user.id))


@router.put("", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsOut:
    row = get_or_create_settings(db, current_user.id)
    updates = payload.model_dump(exclude_unset=True)
    # "********" on the bot token keeps the stored value (same pattern as
    # monitor secret headers); an explicit null clears it (env fallback
    # then applies); a real value replaces it.
    if updates.get("telegram_bot_token") == MASKED_VALUE:
        updates.pop("telegram_bot_token")
    for field_name, value in updates.items():
        setattr(row, field_name, value)
    db.commit()
    db.refresh(row)
    logger.info("settings updated")
    return _to_response(row)


@router.post("/test-notification", response_model=TestNotificationResult)
async def test_notification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestNotificationResult:
    """Send a Telegram test message with the current user's effective config.

    Always returns 200: when Telegram is not configured the body reports
    success=false instead of raising.
    """
    success, detail = await send_test_notification(db, user_id=current_user.id)
    return TestNotificationResult(success=success, detail=detail)


@router.post("/cleanup", response_model=CleanupResult)
def cleanup_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CleanupResult:
    """Run the retention cleanup for the current user's data immediately
    and return what was deleted."""
    counts = run_cleanup(db, user_id=current_user.id)
    logger.info("manual cleanup run records=%s", counts["records_deleted"])
    return CleanupResult(**counts)


@router.get("/cleanup-preview", response_model=CleanupResult)
def cleanup_preview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CleanupResult:
    """Preview what a retention cleanup of the current user's data would
    delete (no deletion)."""
    return CleanupResult(**preview_cleanup(db, user_id=current_user.id))
