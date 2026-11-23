"""Timezone helpers. All timestamps are UTC."""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_naive_utc(value: datetime) -> datetime:
    """Drop tzinfo, treating the value as UTC.

    All timestamps are stored in DATETIME columns without tzinfo (SQLite and
    MySQL both drop it on write), so values read back from the DB are naive
    while freshly computed ones are aware — normalize before comparing.
    """
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
