"""Shared schema helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict


def _ensure_utc(value):
    """SQLite/MySQL DATETIME columns store naive values; treat them as UTC
    so API responses always carry an explicit +00:00 offset."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


UtcDateTime = Annotated[datetime, BeforeValidator(_ensure_utc)]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
