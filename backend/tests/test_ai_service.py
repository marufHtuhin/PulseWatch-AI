"""Gemini AI service: valid replies are used, every failure mode falls back.

The Gemini HTTP transport is mocked via ``client_factory``; no real Gemini
key or network call is ever involved.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.models.alert import Alert
from app.services.ai_service import (
    FALLBACK_TEMPLATES,
    build_prompt,
    fallback_content,
    generate_alert_content,
)
from app.services.anomaly_service import AnomalyFinding
from app.services.monitoring_service import run_check
from tests.conftest import json_response_handler, mock_client_factory

GEMINI_MODEL = "gemini-2.0-flash"


def _gemini_envelope(text: str) -> dict:
    """The JSON shape the Gemini generateContent API returns."""
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _ai_payload(**overrides) -> str:
    payload = {
        "title": "AI: slow endpoint on Test API",
        "severity": "high",
        "summary": "AI summary of the incident.",
        "possible_cause": "AI most-likely cause.",
        "recommended_action": "AI recommended action.",
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture()
def with_gemini_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-for-tests")
    return settings


@pytest.fixture()
def finding():
    return AnomalyFinding(
        "HIGH_RESPONSE_TIME",
        "high",
        "Response time 9000ms exceeded the 3000ms threshold (3.0x).",
    )


@pytest.fixture()
def metrics():
    return {
        "status_code": 200,
        "response_time_ms": 9000.0,
        "response_size_bytes": 1234,
        "records_returned": 5,
        "baseline": {"n": 12, "mean_ms": 100.0, "stddev_ms": 5.0},
    }


async def test_no_api_key_uses_fallback_without_network(
    db, make_monitor, finding, metrics
):
    monitor = make_monitor(name="Test API")
    calls = {"n": 0}

    async def handler(request: httpx.Request):  # noqa: ARG001
        calls["n"] += 1
        return httpx.Response(200, json=_gemini_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is False
    assert calls["n"] == 0  # no key -> Gemini is never contacted
    assert content.title == "High response time on Test API"
    assert content.severity == "high"


async def test_valid_gemini_reply_is_validated_and_used(
    db, make_monitor, finding, metrics, with_gemini_key
):
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):
        # The request must go to the configured Gemini model endpoint.
        assert GEMINI_MODEL in str(request.url)
        assert request.headers["x-goog-api-key"] == "test-key-for-tests"
        return httpx.Response(200, json=_gemini_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is True
    assert content.title == "AI: slow endpoint on Test API"
    assert content.severity == "high"
    assert content.summary == "AI summary of the incident."
    assert content.possible_cause == "AI most-likely cause."
    assert content.recommended_action == "AI recommended action."


@pytest.mark.parametrize(
    "scenario",
    ["http_400", "malformed_json", "wrong_schema", "bad_severity", "connect_error"],
)
async def test_gemini_failures_fall_back_deterministically(
    db, make_monitor, finding, metrics, with_gemini_key, scenario
):
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):  # noqa: ARG001
        if scenario == "http_400":
            return httpx.Response(400, json={"error": {"message": "bad request"}})
        if scenario == "malformed_json":
            return httpx.Response(200, json=_gemini_envelope("{not valid json"))
        if scenario == "wrong_schema":
            # Missing required keys.
            return httpx.Response(
                200, json=_gemini_envelope(json.dumps({"title": "only a title"}))
            )
        if scenario == "bad_severity":
            return httpx.Response(
                200, json=_gemini_envelope(_ai_payload(severity="catastrophic"))
            )
        raise httpx.ConnectError("cannot reach generativelanguage.googleapis.com")

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is False
    # Deterministic fallback: same template every time for this anomaly type.
    assert content.title == "High response time on Test API"
    assert content.severity == "high"
    assert "9000ms" in content.summary


async def test_monitoring_still_completes_when_gemini_fails(
    db, make_monitor, with_gemini_key
):
    """A Gemini outage must never break monitoring: the check completes and
    the alert is created from the fallback template."""
    monitor = make_monitor(latency_threshold_ms=100)

    async def failing_ai(request: httpx.Request):  # noqa: ARG001
        raise httpx.ConnectError("gemini unreachable")

    outcome = await run_check(
        db,
        monitor.id,
        client_factory=mock_client_factory(json_response_handler(delay=0.12)),
        ai_client_factory=mock_client_factory(failing_ai),
    )

    assert outcome.record.is_success is True
    assert outcome.anomalies[0].anomaly_type == "HIGH_RESPONSE_TIME"
    assert len(outcome.alerts_created) == 1
    alert = db.query(Alert).first()
    assert alert.ai_generated is False
    assert alert.title == "High response time on Example API"


async def test_monitoring_uses_ai_content_when_gemini_succeeds(
    db, make_monitor, with_gemini_key
):
    monitor = make_monitor(latency_threshold_ms=100)

    async def good_ai(request: httpx.Request):  # noqa: ARG001
        return httpx.Response(200, json=_gemini_envelope(_ai_payload()))

    outcome = await run_check(
        db,
        monitor.id,
        client_factory=mock_client_factory(json_response_handler(delay=0.12)),
        ai_client_factory=mock_client_factory(good_ai),
    )

    assert len(outcome.alerts_created) == 1
    alert = db.query(Alert).first()
    assert alert.ai_generated is True
    assert alert.title == "AI: slow endpoint on Test API"


# --- prompt + fallback template coverage ------------------------------------

def test_build_prompt_contains_only_metadata(db, make_monitor, finding, metrics):
    monitor = make_monitor(name="Prompt API")
    prompt = build_prompt(monitor, finding, metrics)

    assert "Prompt API" in prompt
    assert "HIGH_RESPONSE_TIME" in prompt
    assert "9000" in prompt  # response time
    assert "3000" in prompt  # threshold
    assert "Baseline" in prompt
    assert "STRICT JSON" in prompt
    # A response body must never appear in the prompt (only metadata is sent).
    assert "secret-body-content" not in prompt


@pytest.mark.parametrize("anomaly_type", sorted(FALLBACK_TEMPLATES))
def test_fallback_template_exists_for_every_anomaly_type(anomaly_type):
    if anomaly_type == "_DEFAULT":
        return
    finding = AnomalyFinding(anomaly_type, "warning", "detail text here")
    content = fallback_content("Some API", finding)
    assert content.title and "Some API" in content.title
    assert content.summary and "detail text here" in content.summary
    assert content.possible_cause
    assert content.recommended_action
    assert content.severity == "warning"


def test_fallback_template_unknown_type_uses_default():
    finding = AnomalyFinding("SOMETHING_NEW", "info", "mystery")
    content = fallback_content("Some API", finding)
    assert content.title == "Anomaly on Some API"
    assert content.severity == "info"
