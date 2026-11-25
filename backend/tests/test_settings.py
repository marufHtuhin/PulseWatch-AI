"""Settings: defaults, partial update persistence, validation."""
from __future__ import annotations

from app.core.config import settings as app_settings
from app.models.settings import AppSettings


def test_get_settings_returns_defaults(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["default_interval_seconds"] == 300
    assert body["default_timeout_seconds"] == 10
    assert body["default_latency_threshold_ms"] == 3000
    assert body["max_concurrency"] == 10
    assert body["ai_configured"] is False  # no key in tests
    assert body["ai_provider"] == "openrouter"  # default provider
    assert body["allow_local_urls"] is False
    assert body["app_env"] == "development"


def test_get_settings_creates_the_single_row(client, db):
    assert db.query(AppSettings).count() == 0
    client.get("/api/settings")
    rows = db.query(AppSettings).all()
    assert len(rows) == 1
    assert rows[0].id == 1


def test_put_partial_update_persists_and_keeps_other_values(client, db):
    first = client.put("/api/settings", json={"default_timeout_seconds": 30})
    assert first.status_code == 200
    body = first.json()
    assert body["default_timeout_seconds"] == 30
    assert body["default_interval_seconds"] == 300  # untouched
    assert body["default_latency_threshold_ms"] == 3000
    assert body["max_concurrency"] == 10

    # A second update stacks on the first; the row stays single.
    second = client.put(
        "/api/settings",
        json={"default_interval_seconds": 60, "max_concurrency": 5},
    )
    assert second.json()["default_timeout_seconds"] == 30
    assert second.json()["default_interval_seconds"] == 60
    assert second.json()["max_concurrency"] == 5
    assert db.query(AppSettings).count() == 1

    # A fresh GET sees the persisted values.
    assert client.get("/api/settings").json()["default_timeout_seconds"] == 30


def test_put_validates_ranges(client):
    assert client.put("/api/settings", json={"max_concurrency": 0}).status_code == 422
    assert client.put("/api/settings", json={"max_concurrency": 51}).status_code == 422
    assert client.put(
        "/api/settings", json={"default_interval_seconds": 29}
    ).status_code == 422
    assert client.put(
        "/api/settings", json={"default_timeout_seconds": 121}
    ).status_code == 422
    assert client.put(
        "/api/settings", json={"default_latency_threshold_ms": 0}
    ).status_code == 422


def test_put_ignores_read_only_fields(client):
    response = client.put(
        "/api/settings",
        json={
            "ai_configured": True,
            "ai_provider": "gemini",
            "app_env": "production",
        },
    )
    assert response.status_code == 200
    # Read-only fields come from env config, not the request body.
    assert response.json()["ai_configured"] is False
    assert response.json()["ai_provider"] == "openrouter"
    assert response.json()["app_env"] == "development"


def test_ai_configured_reflects_openrouter_key(client, monkeypatch):
    monkeypatch.setattr(app_settings, "OPENROUTER_API_KEY", "some-key")
    body = client.get("/api/settings").json()
    assert body["ai_configured"] is True
    assert body["ai_provider"] == "openrouter"


def test_ai_configured_reflects_gemini_key_when_provider_is_gemini(
    client, monkeypatch
):
    monkeypatch.setattr(app_settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(app_settings, "GEMINI_API_KEY", "some-key")
    body = client.get("/api/settings").json()
    assert body["ai_configured"] is True
    assert body["ai_provider"] == "gemini"


def test_ai_configured_false_when_selected_provider_has_no_key(
    client, monkeypatch
):
    # Only the SELECTED provider's key counts: an OpenRouter key does not
    # configure AI when the provider is gemini.
    monkeypatch.setattr(app_settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(app_settings, "OPENROUTER_API_KEY", "some-key")
    body = client.get("/api/settings").json()
    assert body["ai_configured"] is False
    assert body["ai_provider"] == "gemini"
