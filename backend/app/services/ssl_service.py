"""TLS certificate expiry lookup.

Blocking socket work — callers run :func:`fetch_cert_expiry` via
``asyncio.to_thread`` so the event loop is never blocked. Any failure
(DNS, connect, handshake, parse) returns None: an unknown expiry is not
an incident, and cert lookup must never fail a check.
"""
from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.core.logging import get_logger

logger = get_logger("ssl")


def https_host_port(url: str) -> tuple[str, int] | None:
    """(hostname, port) for an https URL, or None for anything else
    (http URLs, unparsable URLs, invalid ports)."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    try:
        port = parsed.port or 443
    except ValueError:
        return None
    return parsed.hostname, port


def fetch_cert_expiry(
    hostname: str, port: int = 443, timeout: float = 10
) -> datetime | None:
    """Return the peer certificate's notAfter as a naive UTC datetime.

    Naive (not aware) to match the codebase's DATETIME storage convention:
    all timestamps are UTC and stored without tzinfo. The TLS handshake
    uses SNI (``server_hostname``) and full chain verification, so an
    expired or invalid certificate yields None — an expired cert is still
    detected, because the expiry stored from an earlier successful fetch
    keeps aging and the SSL_EXPIRING rule fires on the stored value.
    """
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as secure:
                cert = secure.getpeercert()
        not_after = cert.get("notAfter") if cert else None
        if not not_after:
            return None
        epoch = ssl.cert_time_to_seconds(not_after)
        return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)
    except Exception as exc:  # noqa: BLE001 - any cert failure is "unknown"
        logger.warning(
            "cert fetch failed host=%s (%s)", hostname, type(exc).__name__
        )
        return None
