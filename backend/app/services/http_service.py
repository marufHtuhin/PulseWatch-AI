"""Real HTTP checks against monitored APIs.

- Async httpx with a manual redirect loop (max 5 hops); every redirect
  target is re-validated against the SSRF policy before being fetched.
- Response bodies are read only up to a hard byte cap and are NEVER stored;
  only metadata (status, size, timings, JSON validity, record count) is kept.
- The httpx client is injectable via ``client_factory`` for tests.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.core.logging import get_logger, sanitize_url
from app.core.security import SSRFBlockedError, validate_url
from app.models.monitor import Monitor
from app.services.http_client import build_async_client

logger = get_logger("http")

MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
# Keys whose list value counts as "the records" when the body is a JSON object.
RECORD_LIST_KEYS = ("data", "items", "results", "records")


@dataclass
class CheckResult:
    status_code: int | None = None
    response_time_ms: float | None = None
    response_size_bytes: int = 0
    content_type: str | None = None
    is_valid_json: bool | None = None
    # Parsed JSON, kept in memory only for the anomaly engine. Never stored.
    json_data: Any = None
    records_returned: int | None = None
    error_message: str | None = None
    # timeout | network | ssrf | None
    error_kind: str | None = None
    final_url: str = ""
    truncated: bool = False


def count_records(data: Any) -> int | None:
    """How many records a parsed JSON body represents."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in RECORD_LIST_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        return 1
    if data is None:
        return None
    return 1


def find_missing_fields(json_data: Any, expected_fields: list[str]) -> list[str]:
    """Expected fields absent from the JSON body (checked against the first
    list item for array bodies, or the object itself)."""
    if not expected_fields or json_data is None:
        return []
    if isinstance(json_data, list):
        if not json_data:
            return []  # ZERO_RECORDS covers the empty case.
        sample = json_data[0] if isinstance(json_data[0], dict) else None
    elif isinstance(json_data, dict):
        sample = json_data
    else:
        return list(expected_fields)
    if sample is None:
        return list(expected_fields)
    return [f for f in expected_fields if f not in sample]


def _safe_error_message(exc: httpx.HTTPError) -> str:
    """Error text that never includes the request URL (it may hold secrets)."""
    if isinstance(exc, httpx.ConnectError):
        return "Connection failed (DNS/network)"
    if isinstance(exc, httpx.ReadTimeout):
        return "Read timed out"
    return type(exc).__name__


async def _read_final_response(
    response: httpx.Response,
    result: CheckResult,
    started_at: float,
    monitor: Monitor,
    max_read_bytes: int,
) -> CheckResult:
    result.status_code = response.status_code
    result.content_type = response.headers.get("content-type")

    size = 0
    chunks: list[bytes] = []
    truncated = False
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size <= max_read_bytes:
            chunks.append(chunk)
        else:
            truncated = True
            break
    body = b"".join(chunks)
    result.response_size_bytes = size
    result.truncated = truncated
    result.response_time_ms = (time.perf_counter() - started_at) * 1000

    content_type = (result.content_type or "").lower()
    expect_json = (
        "json" in content_type
        or bool(monitor.expected_fields)
        or bool(monitor.check_zero_records)
    )
    if expect_json:
        if truncated:
            # Could not read the whole body: validity is unknown, not invalid.
            result.is_valid_json = None
        elif not body:
            result.is_valid_json = False
        else:
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
                result.is_valid_json = True
                result.json_data = data
                result.records_returned = count_records(data)
            except json.JSONDecodeError:
                result.is_valid_json = False
    return result


async def perform_check(
    monitor: Monitor,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> CheckResult:
    """Run one real HTTP check for a monitor and return its metadata."""
    result = CheckResult(final_url=monitor.url)
    allow_local = settings.ALLOW_LOCAL_URLS
    headers = dict(monitor.headers or {})
    method = monitor.method.upper()
    body = monitor.request_body if method in ("POST", "PUT") else None
    current_url = monitor.url
    max_read = settings.MAX_RESPONSE_READ_BYTES
    started_at = time.perf_counter()

    # The client is created lazily, only after the first URL passes SSRF
    # validation, so blocked checks never open a connection at all.
    client: httpx.AsyncClient | None = None
    try:
        for hop in range(MAX_REDIRECTS + 1):
            try:
                await validate_url(current_url, allow_local=allow_local)
            except SSRFBlockedError as exc:
                result.error_kind = "ssrf"
                result.error_message = str(exc)
                result.response_time_ms = (time.perf_counter() - started_at) * 1000
                logger.warning(
                    "check blocked monitor_id=%s url=%s reason=%s",
                    monitor.id,
                    sanitize_url(current_url),
                    exc,
                )
                return result
            if client is None:
                client = (
                    client_factory()
                    if client_factory
                    else build_async_client(current_url, follow_redirects=False)
                )
            try:
                async with client.stream(
                    method,
                    current_url,
                    headers=headers,
                    content=body,
                    timeout=monitor.timeout_seconds,
                ) as response:
                    if (
                        response.status_code in REDIRECT_STATUSES
                        and "location" in response.headers
                    ):
                        if hop >= MAX_REDIRECTS:
                            # Redirect budget exhausted: treat as final.
                            return await _read_final_response(
                                response, result, started_at, monitor, max_read
                            )
                        next_url = urljoin(current_url, response.headers["location"])
                        if response.status_code in (301, 302, 303):
                            method = "GET"
                            body = None
                        current_url = next_url
                        result.final_url = current_url
                        continue
                    return await _read_final_response(
                        response, result, started_at, monitor, max_read
                    )
            except httpx.TimeoutException:
                result.error_kind = "timeout"
                result.error_message = f"Request timed out after {monitor.timeout_seconds}s"
                result.response_time_ms = (time.perf_counter() - started_at) * 1000
                return result
            except httpx.HTTPError as exc:
                result.error_kind = "network"
                result.error_message = _safe_error_message(exc)
                result.response_time_ms = (time.perf_counter() - started_at) * 1000
                return result
    finally:
        if client is not None:
            await client.aclose()
    return result
