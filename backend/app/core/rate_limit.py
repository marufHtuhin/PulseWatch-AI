"""Shared slowapi rate limiter for the auth endpoints.

- Key: the first entry of the ``X-Forwarded-For`` header (Render sits in
  front and sets it), falling back to the direct client IP. Without the
  header handling every request would share Render's proxy IP and one
  abusive client would lock everyone out.
- DISABLED when ``settings.TESTING`` is True (``enabled=not
  settings.TESTING``): the existing test suite must not be rate-limited.
  slowapi checks ``limiter.enabled`` on every request, so tests can flip
  ``limiter.enabled = True`` at runtime to exercise the 429 path and flip
  it back afterwards.
- In-memory limiting is per-instance: with multiple Render instances each
  keeps its own counters, so the effective limit is N x the configured
  rate. Redis-backed limiting (slowapi supports it via ``storage_uri``)
  is the multi-instance upgrade if that ever matters.
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _rate_limit_key(request: Request) -> str:
    """Client identity for rate limiting: first X-Forwarded-For entry,
    else the direct client IP."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, enabled=not settings.TESTING)
