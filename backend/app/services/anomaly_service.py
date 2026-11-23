"""Deterministic anomaly engine — all 10 rules, each a separate testable
function. No ML, no randomness: the same check input always yields the
same findings.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# Minimum history points before the historical rule may fire. This is what
# keeps the rule from producing false positives on a new monitor.
HISTORICAL_MIN_POINTS = 10
HISTORY_WINDOW = 30


@dataclass
class AnomalyFinding:
    anomaly_type: str
    severity: str  # info | warning | high | critical
    description: str


@dataclass
class AnomalyContext:
    response_time_ms: float | None = None
    latency_threshold_ms: int = 3000
    status_code: int | None = None
    expected_status_codes: list[int] = field(default_factory=lambda: [200])
    error_kind: str | None = None  # timeout | network | ssrf | None
    records_returned: int | None = None
    check_zero_records: bool = False
    is_valid_json: bool | None = None
    expected_json: bool = False
    missing_fields: list[str] = field(default_factory=list)
    response_size_bytes: int = 0
    max_response_size_bytes: int = 1048576
    history_ms: list[float] = field(default_factory=list)


def check_high_response_time(
    response_time_ms: float | None, threshold_ms: int
) -> AnomalyFinding | None:
    """Severity tiers: >1x threshold warning, >=2x high, >=4x critical."""
    if response_time_ms is None or response_time_ms <= threshold_ms:
        return None
    ratio = response_time_ms / threshold_ms if threshold_ms > 0 else float("inf")
    severity = "warning" if ratio < 2 else "high" if ratio < 4 else "critical"
    return AnomalyFinding(
        "HIGH_RESPONSE_TIME",
        severity,
        f"Response time {response_time_ms:.0f}ms exceeded the {threshold_ms}ms "
        f"threshold ({ratio:.1f}x).",
    )


def check_http_error(status_code: int | None) -> AnomalyFinding | None:
    if status_code is None or status_code < 400:
        return None
    severity = "high" if status_code >= 500 else "warning"
    return AnomalyFinding(
        "HTTP_ERROR", severity, f"HTTP error status {status_code} returned."
    )


def check_timeout(error_kind: str | None) -> AnomalyFinding | None:
    if error_kind != "timeout":
        return None
    return AnomalyFinding(
        "TIMEOUT", "high", "Request timed out before a response was received."
    )


def check_network_error(error_kind: str | None) -> AnomalyFinding | None:
    """Connection/DNS/SSL failures: the API could not be reached at all.
    SSRF blocks (error_kind "ssrf") deliberately do NOT fire this rule —
    a rejected URL is a configuration/policy outcome, not the API going down.
    """
    if error_kind != "network":
        return None
    return AnomalyFinding(
        "NETWORK_ERROR",
        "high",
        "Could not connect to the API (DNS failure, connection refused, or "
        "network/SSL error) — no response was received.",
    )


def check_zero_records(
    records_returned: int | None, check_zero_records: bool
) -> AnomalyFinding | None:
    if not check_zero_records or records_returned is None or records_returned != 0:
        return None
    return AnomalyFinding(
        "ZERO_RECORDS", "warning", "API returned zero records."
    )


def check_invalid_response(
    is_valid_json: bool | None, expected_json: bool
) -> AnomalyFinding | None:
    if not expected_json or is_valid_json is not False:
        return None
    return AnomalyFinding(
        "INVALID_RESPONSE", "high", "Response body is not valid JSON."
    )


def check_missing_fields(missing_fields: list[str]) -> AnomalyFinding | None:
    if not missing_fields:
        return None
    return AnomalyFinding(
        "MISSING_FIELDS",
        "warning",
        f"Expected field(s) missing from response: {', '.join(missing_fields)}.",
    )


def check_large_response(size_bytes: int, max_bytes: int) -> AnomalyFinding | None:
    if size_bytes <= max_bytes:
        return None
    ratio = size_bytes / max_bytes if max_bytes > 0 else float("inf")
    severity = "high" if ratio >= 5 else "warning"
    return AnomalyFinding(
        "LARGE_RESPONSE",
        severity,
        f"Response size {size_bytes} bytes exceeded the {max_bytes} byte limit.",
    )


def check_unexpected_status(
    status_code: int | None, expected_status_codes: list[int]
) -> AnomalyFinding | None:
    # 4xx/5xx are covered by HTTP_ERROR; this rule is for unexpected
    # non-error statuses (e.g. 201 when 200 was expected, un-followed 3xx).
    if status_code is None or status_code >= 400:
        return None
    if status_code in (expected_status_codes or []):
        return None
    return AnomalyFinding(
        "UNEXPECTED_STATUS",
        "warning",
        f"Unexpected status {status_code}; expected one of {expected_status_codes}.",
    )


def check_historical_anomaly(
    response_time_ms: float | None, history_ms: list[float]
) -> AnomalyFinding | None:
    """Rolling mean + stddev over recent checks. Requires >= 10 history
    points, so a new monitor can never trigger it."""
    if response_time_ms is None or len(history_ms) < HISTORICAL_MIN_POINTS:
        return None
    mean = statistics.fmean(history_ms)
    if mean <= 0:
        return None
    stdev = statistics.stdev(history_ms) if len(history_ms) > 1 else 0.0
    if stdev <= 0:
        # No variance in history: only flag an extreme (2x) jump.
        if response_time_ms > mean * 2:
            return AnomalyFinding(
                "HISTORICAL_ANOMALY",
                "warning",
                f"Response time {response_time_ms:.0f}ms is over 2x the historical "
                f"mean {mean:.0f}ms (no variance in history).",
            )
        return None
    z = (response_time_ms - mean) / stdev
    if z <= 2:
        return None
    severity = "high" if z > 3 else "warning"
    return AnomalyFinding(
        "HISTORICAL_ANOMALY",
        severity,
        f"Response time {response_time_ms:.0f}ms deviates from the historical "
        f"mean {mean:.0f}ms (stddev {stdev:.0f}ms, z={z:.1f}).",
    )


def detect_anomalies(ctx: AnomalyContext) -> list[AnomalyFinding]:
    """Run all 10 rules against one check and return every finding."""
    checks = [
        check_high_response_time(ctx.response_time_ms, ctx.latency_threshold_ms),
        check_http_error(ctx.status_code),
        check_timeout(ctx.error_kind),
        check_network_error(ctx.error_kind),
        check_zero_records(ctx.records_returned, ctx.check_zero_records),
        check_invalid_response(ctx.is_valid_json, ctx.expected_json),
        check_missing_fields(ctx.missing_fields),
        check_large_response(ctx.response_size_bytes, ctx.max_response_size_bytes),
        check_unexpected_status(ctx.status_code, ctx.expected_status_codes),
        check_historical_anomaly(ctx.response_time_ms, ctx.history_ms),
    ]
    return [finding for finding in checks if finding is not None]
