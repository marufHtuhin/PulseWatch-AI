"""OpenRouter AI service (v4.3 default provider): valid replies are used,
every failure mode falls back, and provider selection routes correctly.

The OpenRouter HTTP transport is mocked via ``client_factory``; no real
OpenRouter key or network call is ever involved. Gemini-path tests live in
test_ai_service.py.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings, settings
from app.services.ai_service import generate_alert_content
from app.services.anomaly_service import AnomalyFinding
from tests.conftest import mock_client_factory

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "nvidia/nemotron-3.5-lightning:free"
OPENROUTER_FALLBACK_MODEL = "google/gemma-4-26b-a4b-it:free"


def _openrouter_envelope(text: str) -> dict:
    """The JSON shape the OpenRouter chat-completions API returns."""
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


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
def with_openrouter_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-openrouter-key")
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


def test_default_ai_provider_is_openrouter():
    # A fresh Settings (not the shared singleton) pins the shipped default
    # regardless of what other tests monkeypatched.
    assert Settings().AI_PROVIDER == "openrouter"
    assert Settings().OPENROUTER_MODEL == OPENROUTER_MODEL
    assert Settings().OPENROUTER_FALLBACK_MODELS == OPENROUTER_FALLBACK_MODEL


async def test_valid_openrouter_reply_is_validated_and_used(
    db, make_monitor, finding, metrics, with_openrouter_key
):
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):
        # The request must go to the OpenRouter chat-completions endpoint
        # with the default model and a Bearer key.
        assert str(request.url) == OPENROUTER_URL
        assert request.headers["Authorization"] == "Bearer test-openrouter-key"
        assert json.loads(request.content)["model"] == OPENROUTER_MODEL
        return httpx.Response(200, json=_openrouter_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is True
    assert content.title == "AI: slow endpoint on Test API"
    assert content.severity == "high"
    assert content.summary == "AI summary of the incident."
    assert content.possible_cause == "AI most-likely cause."
    assert content.recommended_action == "AI recommended action."


async def test_openrouter_request_sends_models_fallback_list(
    db, make_monitor, finding, metrics, with_openrouter_key, monkeypatch
):
    """The request body carries OpenRouter's `models` array — primary
    first, then the comma-separated fallbacks in order — so OpenRouter
    tries them in sequence if the primary is down or rate-limited
    (https://openrouter.ai/docs/guides/routing/model-fallbacks)."""
    monkeypatch.setattr(
        settings,
        "OPENROUTER_FALLBACK_MODELS",
        "google/gemma-4-26b-a4b-it:free, meta-llama/llama-3.3-70b-instruct:free",
    )
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body["model"] == OPENROUTER_MODEL
        assert body["models"] == [
            OPENROUTER_MODEL,
            "google/gemma-4-26b-a4b-it:free",
            "meta-llama/llama-3.3-70b-instruct:free",
        ]
        return httpx.Response(200, json=_openrouter_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is True
    assert content.title == "AI: slow endpoint on Test API"


async def test_openrouter_429_falls_back(
    db, make_monitor, finding, metrics, with_openrouter_key
):
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):  # noqa: ARG001
        return httpx.Response(
            429, json={"error": {"message": "rate limited", "code": 429}}
        )

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is False
    assert content.title == "High response time on Test API"
    assert content.severity == "high"
    assert "9000ms" in content.summary


async def test_openrouter_bad_json_falls_back(
    db, make_monitor, finding, metrics, with_openrouter_key
):
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):  # noqa: ARG001
        return httpx.Response(
            200, json=_openrouter_envelope("not json{")
        )

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is False
    assert content.title == "High response time on Test API"
    assert content.severity == "high"


async def test_no_openrouter_key_uses_fallback_without_network(
    db, make_monitor, finding, metrics, monkeypatch
):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)
    monitor = make_monitor(name="Test API")
    calls = {"n": 0}

    async def handler(request: httpx.Request):  # noqa: ARG001
        calls["n"] += 1
        return httpx.Response(200, json=_openrouter_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is False
    assert calls["n"] == 0  # no key -> OpenRouter is never contacted
    assert content.title == "High response time on Test API"
    assert content.severity == "high"


async def test_default_provider_prefers_openrouter_when_both_keys_set(
    db, make_monitor, finding, metrics, with_openrouter_key, monkeypatch
):
    """With both keys set and no explicit provider, the default
    (openrouter) wins — the request must go to OpenRouter, not Gemini."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-for-tests")
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):
        assert "openrouter.ai" in str(request.url)
        assert "generativelanguage.googleapis.com" not in str(request.url)
        return httpx.Response(200, json=_openrouter_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is True
    assert content.title == "AI: slow endpoint on Test API"


async def test_gemini_provider_routes_to_gemini(
    db, make_monitor, finding, metrics, monkeypatch
):
    """With AI_PROVIDER=gemini the Gemini path is used — the OpenRouter
    endpoint is never hit."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-for-tests")
    monitor = make_monitor(name="Test API")

    async def handler(request: httpx.Request):
        assert "generativelanguage.googleapis.com" in str(request.url)
        assert "openrouter.ai" not in str(request.url)
        assert request.headers["x-goog-api-key"] == "test-key-for-tests"
        return httpx.Response(200, json=_gemini_envelope(_ai_payload()))

    content, ai_generated = await generate_alert_content(
        monitor, finding, metrics, client_factory=mock_client_factory(handler)
    )

    assert ai_generated is True
    assert content.title == "AI: slow endpoint on Test API"
    assert content.severity == "high"
