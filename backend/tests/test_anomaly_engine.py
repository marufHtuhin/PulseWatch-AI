"""Deterministic anomaly engine — all 10 rules, tested individually.

These tests call the rule functions directly (no HTTP, no DB) so every
severity tier and boundary is exercised exactly.
"""
from __future__ import annotations

import pytest

from app.services.anomaly_service import (
    HISTORICAL_MIN_POINTS,
    AnomalyContext,
    check_high_response_time,
    check_historical_anomaly,
    check_http_error,
    check_invalid_response,
    check_large_response,
    check_missing_fields,
    check_network_error,
    check_timeout,
    check_unexpected_status,
    check_zero_records,
    detect_anomalies,
)


# --- HIGH_RESPONSE_TIME (severity tiers) ------------------------------------

@pytest.mark.parametrize(
    "rt_ms, threshold, expected_severity",
    [
        (1500, 1000, "warning"),   # 1.5x
        (1999, 1000, "warning"),   # just under 2x
        (2000, 1000, "high"),      # exactly 2x
        (3999, 1000, "high"),      # just under 4x
        (4000, 1000, "critical"),  # exactly 4x
        (12000, 1000, "critical"), # 12x
    ],
)
def test_high_response_time_tiers(rt_ms, threshold, expected_severity):
    finding = check_high_response_time(rt_ms, threshold)
    assert finding is not None
    assert finding.anomaly_type == "HIGH_RESPONSE_TIME"
    assert finding.severity == expected_severity
    assert str(threshold) in finding.description


@pytest.mark.parametrize("rt_ms, threshold", [(1000, 1000), (999, 1000), (0, 1000)])
def test_high_response_time_no_fire_at_or_below_threshold(rt_ms, threshold):
    assert check_high_response_time(rt_ms, threshold) is None


def test_high_response_time_no_fire_without_timing():
    assert check_high_response_time(None, 1000) is None


# --- HTTP_ERROR -------------------------------------------------------------

@pytest.mark.parametrize("status", [200, 201, 301, 399])
def test_http_error_no_fire_below_400(status):
    assert check_http_error(status) is None


@pytest.mark.parametrize("status, severity", [(400, "warning"), (404, "warning"), (499, "warning")])
def test_http_error_4xx_is_warning(status, severity):
    finding = check_http_error(status)
    assert finding.anomaly_type == "HTTP_ERROR"
    assert finding.severity == severity


@pytest.mark.parametrize("status", [500, 502, 503])
def test_http_error_5xx_is_high(status):
    finding = check_http_error(status)
    assert finding.anomaly_type == "HTTP_ERROR"
    assert finding.severity == "high"


def test_http_error_no_fire_without_status():
    assert check_http_error(None) is None


# --- TIMEOUT ----------------------------------------------------------------

def test_timeout_fires_only_for_timeout_kind():
    finding = check_timeout("timeout")
    assert finding is not None
    assert finding.anomaly_type == "TIMEOUT"
    assert finding.severity == "high"
    assert check_timeout("network") is None
    assert check_timeout("ssrf") is None
    assert check_timeout(None) is None


# --- NETWORK_ERROR ----------------------------------------------------------

def test_network_error_fires_only_for_network_kind():
    finding = check_network_error("network")
    assert finding is not None
    assert finding.anomaly_type == "NETWORK_ERROR"
    assert finding.severity == "high"
    # Timeouts have their own rule; SSRF blocks are policy outcomes, not
    # API failures, and must not raise an alert.
    assert check_network_error("timeout") is None
    assert check_network_error("ssrf") is None
    assert check_network_error(None) is None


# --- ZERO_RECORDS -----------------------------------------------------------

def test_zero_records_fires_only_when_enabled_and_empty():
    finding = check_zero_records(0, True)
    assert finding is not None
    assert finding.anomaly_type == "ZERO_RECORDS"
    assert finding.severity == "warning"
    assert check_zero_records(0, False) is None  # check disabled
    assert check_zero_records(3, True) is None   # records present
    assert check_zero_records(None, True) is None  # unknown count


# --- INVALID_RESPONSE -------------------------------------------------------

def test_invalid_response_fires_only_when_json_expected_and_invalid():
    finding = check_invalid_response(False, True)
    assert finding is not None
    assert finding.anomaly_type == "INVALID_RESPONSE"
    assert finding.severity == "high"
    assert check_invalid_response(False, False) is None  # JSON not expected
    assert check_invalid_response(True, True) is None    # valid JSON
    assert check_invalid_response(None, True) is None    # unknown validity


# --- MISSING_FIELDS ---------------------------------------------------------

def test_missing_fields_lists_absent_names():
    finding = check_missing_fields(["title", "email"])
    assert finding is not None
    assert finding.anomaly_type == "MISSING_FIELDS"
    assert finding.severity == "warning"
    assert "title" in finding.description
    assert "email" in finding.description
    assert check_missing_fields([]) is None


# --- LARGE_RESPONSE ---------------------------------------------------------

def test_large_response_tiers():
    assert check_large_response(100, 100) is None
    assert check_large_response(99, 100) is None
    warning = check_large_response(300, 100)
    assert warning.anomaly_type == "LARGE_RESPONSE"
    assert warning.severity == "warning"  # 3x
    high = check_large_response(500, 100)
    assert high.severity == "high"  # 5x


# --- UNEXPECTED_STATUS ------------------------------------------------------

def test_unexpected_status_fires_for_non_error_mismatch():
    finding = check_unexpected_status(201, [200])
    assert finding is not None
    assert finding.anomaly_type == "UNEXPECTED_STATUS"
    assert finding.severity == "warning"
    assert check_unexpected_status(200, [200]) is None
    assert check_unexpected_status(201, [200, 201]) is None
    # 4xx/5xx belong to HTTP_ERROR, not this rule.
    assert check_unexpected_status(500, [200]) is None
    assert check_unexpected_status(404, [200]) is None
    assert check_unexpected_status(None, [200]) is None


# --- HISTORICAL_ANOMALY -----------------------------------------------------

def test_historical_anomaly_needs_at_least_10_points():
    # 9 history points, even with a 10x jump, must NOT fire.
    assert HISTORICAL_MIN_POINTS == 10
    assert check_historical_anomaly(1000, [100.0] * 9) is None
    # The 10th point unlocks the rule.
    assert check_historical_anomaly(1000, [100.0] * 10) is not None


def test_historical_anomaly_no_false_positive_within_two_stddevs():
    history = [95.0, 100.0, 105.0, 98.0, 102.0, 99.0, 101.0, 100.0, 97.0, 103.0]
    # mean ~100, stddev ~3: 105ms is well within 2 stddevs.
    assert check_historical_anomaly(105, history) is None
    assert check_historical_anomaly(90, history) is None  # faster is never an anomaly


def test_historical_anomaly_fires_when_latency_far_above_baseline():
    history = [95.0, 100.0, 105.0, 98.0, 102.0, 99.0, 101.0, 100.0, 97.0, 103.0]
    finding = check_historical_anomaly(500, history)
    assert finding is not None
    assert finding.anomaly_type == "HISTORICAL_ANOMALY"
    assert finding.severity == "high"  # z-score far above 3


def test_historical_anomaly_warning_band_between_2_and_3_stddevs():
    # Mean 100, sample stddev ~7.45; 120ms is ~2.7 stddevs above the mean.
    history = [90.0, 95.0, 100.0, 105.0, 110.0, 90.0, 95.0, 100.0, 105.0, 110.0]
    finding = check_historical_anomaly(120, history)
    assert finding is not None
    assert finding.severity == "warning"


def test_historical_anomaly_zero_variance_needs_2x_jump():
    history = [100.0] * 12  # identical timings -> stddev 0
    assert check_historical_anomaly(150, history) is None  # 1.5x: not enough
    assert check_historical_anomaly(200, history) is None  # exactly 2x: not over
    finding = check_historical_anomaly(201, history)
    assert finding is not None
    assert finding.anomaly_type == "HISTORICAL_ANOMALY"


def test_historical_anomaly_ignores_missing_or_zero_baseline():
    assert check_historical_anomaly(None, [100.0] * 12) is None
    assert check_historical_anomaly(500, [0.0] * 12) is None


# --- detect_anomalies (combined) --------------------------------------------

def test_detect_anomalies_clean_context_returns_empty():
    findings = detect_anomalies(
        AnomalyContext(
            response_time_ms=120.0,
            latency_threshold_ms=3000,
            status_code=200,
            expected_status_codes=[200],
            records_returned=5,
            check_zero_records=True,
            is_valid_json=True,
            expected_json=True,
            missing_fields=[],
            response_size_bytes=500,
            max_response_size_bytes=1048576,
            history_ms=[100.0] * 12,
        )
    )
    assert findings == []


def test_detect_anomalies_returns_every_triggered_rule():
    findings = detect_anomalies(
        AnomalyContext(
            response_time_ms=9000.0,  # 3x threshold -> HIGH_RESPONSE_TIME (high)
            latency_threshold_ms=3000,
            status_code=500,  # -> HTTP_ERROR (high)
            expected_status_codes=[200],
            records_returned=0,
            check_zero_records=True,  # -> ZERO_RECORDS (warning)
            is_valid_json=True,
            expected_json=True,
            missing_fields=["title"],  # -> MISSING_FIELDS (warning)
            response_size_bytes=3000,
            max_response_size_bytes=1000,  # 3x -> LARGE_RESPONSE (warning)
            history_ms=[100.0] * 12,  # 9000ms vs ~100ms baseline
        )
    )
    types = {f.anomaly_type for f in findings}
    assert types == {
        "HIGH_RESPONSE_TIME",
        "HTTP_ERROR",
        "ZERO_RECORDS",
        "MISSING_FIELDS",
        "LARGE_RESPONSE",
        "HISTORICAL_ANOMALY",
    }
    # TIMEOUT / INVALID_RESPONSE / UNEXPECTED_STATUS must NOT fire here.
    assert "TIMEOUT" not in types
    assert "INVALID_RESPONSE" not in types
    assert "UNEXPECTED_STATUS" not in types
