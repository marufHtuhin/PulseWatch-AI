"""SSRF protection and secret-header handling.

SSRF rules (per API contract):
- Only http/https URLs are allowed.
- The hostname is resolved at check time and EVERY resolved IP is validated:
  loopback, private, link-local, reserved, and multicast addresses are
  rejected (``ip.is_global`` must be True).
- Cloud metadata hostnames/IPs are always rejected.
- Redirect targets are re-validated on every hop (see http_service).
- ``ALLOW_LOCAL_URLS=true`` is a dev-only override that permits non-public
  IPs; metadata hostnames/IPs are still blocked even then.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

SECRET_HEADER_NAMES = {"authorization", "x-api-key", "api-key", "cookie", "x-auth-token"}
MASKED_VALUE = "********"
METADATA_HOSTNAMES = {"metadata.google.internal", "metadata.google.com", "metadata"}
METADATA_IPS = {ipaddress.ip_address("169.254.169.254")}


class SSRFBlockedError(ValueError):
    """Raised when a URL fails SSRF validation."""


# ---------------------------------------------------------------------------
# Secret headers
# ---------------------------------------------------------------------------

def is_secret_header(name: str) -> bool:
    return name.lower() in SECRET_HEADER_NAMES


def mask_headers(headers: dict | None) -> dict:
    """Return a copy of ``headers`` with secret values replaced by ``********``."""
    if not headers:
        return {}
    return {k: (MASKED_VALUE if is_secret_header(k) else v) for k, v in headers.items()}


def merge_headers(stored: dict | None, incoming: dict | None) -> dict:
    """Full-replace merge for updates.

    ``incoming`` replaces ``stored`` entirely, except that a secret header
    whose value is exactly ``"********"`` keeps the stored value.
    Header-name matching is case-insensitive.
    """
    stored = stored or {}
    if incoming is None:
        return {}
    stored_lower = {k.lower(): v for k, v in stored.items()}
    merged: dict = {}
    for key, value in incoming.items():
        if value == MASKED_VALUE and is_secret_header(key) and key.lower() in stored_lower:
            merged[key] = stored_lower[key.lower()]
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# SSRF validation
# ---------------------------------------------------------------------------

async def _resolve_all(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to every IP it currently maps to."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS resolution failed for host '{hostname}'") from exc
    ips: list = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if str(ip) not in seen:
            seen.add(str(ip))
            ips.append(ip)
    if not ips:
        raise SSRFBlockedError(f"No IP addresses resolved for host '{hostname}'")
    return ips


async def validate_url(url: str, allow_local: bool = False) -> str:
    """Validate a URL against the SSRF policy.

    Returns the (stripped) URL on success, raises :class:`SSRFBlockedError`
    otherwise. DNS is resolved at call time so every check re-validates.
    """
    if not url or not isinstance(url, str):
        raise SSRFBlockedError("URL is empty")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(
            f"Blocked URL scheme '{parsed.scheme or '(none)'}': only http/https are allowed"
        )
    host = parsed.hostname
    if not host:
        raise SSRFBlockedError("URL has no hostname")
    host_lower = host.lower()
    if host_lower in METADATA_HOSTNAMES:
        raise SSRFBlockedError(f"Blocked metadata hostname '{host}'")

    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        ips = await _resolve_all(host)

    for ip in ips:
        if ip in METADATA_IPS:
            raise SSRFBlockedError(f"Blocked metadata IP '{ip}'")
        # NOTE: ip.is_global is True for multicast addresses (224.0.0.0/4,
        # ff00::/8) in CPython, so multicast needs an explicit check —
        # otherwise a monitor could be pointed at a multicast group.
        if not allow_local and (not ip.is_global or ip.is_multicast):
            raise SSRFBlockedError(
                f"Blocked non-public IP '{ip}' for host '{host}' "
                "(loopback/private/link-local/reserved/multicast)"
            )
    return url
