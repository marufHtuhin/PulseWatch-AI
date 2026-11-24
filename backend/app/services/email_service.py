"""Email sending via the Brevo HTTP API (password-reset OTP codes).

- Config: BREVO_API_KEY + EMAIL_FROM env vars. EMAIL_FROM must be a
  sender address verified in the Brevo account (a verified Gmail address
  works — no domain needed).
- The API key and the OTP are NEVER logged; logs carry only the
  recipient and success/failure.
- Sending never raises: any failure (unconfigured, network error,
  non-2xx) logs a warning and returns False, so a mail problem never
  breaks the forgot-password endpoint (it always returns its generic
  200).
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("email")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
EMAIL_TIMEOUT_SECONDS = 10.0
RESET_SUBJECT = "PulseWatch — password reset code"


def _reset_email_html(otp: str) -> str:
    return (
        "<div style=\"font-family: sans-serif; max-width: 480px; "
        "margin: 0 auto; color: #111827;\">"
        "<h2 style=\"font-size: 20px;\">Your PulseWatch password reset code</h2>"
        "<p>Use this code to reset your password:</p>"
        f"<p style=\"font-size: 32px; font-weight: bold; letter-spacing: 6px; "
        f"margin: 16px 0;\">{otp}</p>"
        "<p>This code expires in 10 minutes.</p>"
        "<p style=\"color: #6b7280; font-size: 14px;\">If you didn't request "
        "a password reset, ignore this email — your password will stay the "
        "same.</p>"
        "</div>"
    )


def send_password_reset_email(to_email: str, otp: str) -> bool:
    """Send the 6-digit reset code to ``to_email`` via Brevo.

    Returns True only on a 2xx response. Returns False (never raises)
    when Brevo is not configured or the send fails.
    """
    api_key = settings.BREVO_API_KEY
    sender = settings.EMAIL_FROM
    if not api_key or not sender:
        logger.warning(
            "password reset email not sent: Brevo not configured "
            "(BREVO_API_KEY / EMAIL_FROM missing) to=%s",
            to_email,
        )
        return False
    # trust_env=False: httpx reads proxy config from the environment by
    # default and crashes on malformed no_proxy entries (see
    # app.services.http_client for the same reasoning).
    try:
        with httpx.Client(
            trust_env=False, timeout=EMAIL_TIMEOUT_SECONDS
        ) as client:
            response = client.post(
                BREVO_API_URL,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json={
                    "sender": {"email": sender},
                    "to": [{"email": to_email}],
                    "subject": RESET_SUBJECT,
                    "htmlContent": _reset_email_html(otp),
                },
            )
    except Exception as exc:  # noqa: BLE001 - email failure is not fatal
        logger.warning(
            "password reset email failed to=%s (%s)", to_email, type(exc).__name__
        )
        return False
    if 200 <= response.status_code < 300:
        logger.info("password reset email sent to=%s", to_email)
        return True
    logger.warning(
        "password reset email failed to=%s status=%s",
        to_email,
        response.status_code,
    )
    return False
