"""Pytest fixtures for PulseWatch AI.

Environment is configured BEFORE any ``app.*`` module is imported:
- ``PULSEWATCH_TESTING=1`` so the scheduler never starts under pytest
  (``GET /health`` then reports the scheduler as "disabled").
- ``DATABASE_URL`` points at a throwaway SQLite file in a temp dir, so the
  real dev database (``backend/pulsewatch.db``) is never touched.
- ``GEMINI_API_KEY`` is empty so AI tests opt in explicitly.
- DNS is mocked to a public IP by default: this sandbox resolves public
  hostnames to CGNAT addresses, which the SSRF policy correctly rejects, so
  mocked checks would otherwise be blocked before the transport runs. SSRF
  tests re-patch DNS with their own values.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import tempfile

import pytest

# --- environment setup (must precede any `app.*` import) -------------------
_TEST_DIR = tempfile.mkdtemp(prefix="pulsewatch-test-")
os.environ["PULSEWATCH_TESTING"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/test.db"
os.environ["GEMINI_API_KEY"] = ""
os.environ["ALLOW_LOCAL_URLS"] = "false"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import security  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.connection import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.monitor import Monitor  # noqa: E402
from app.services import monitoring_service  # noqa: E402

PUBLIC_IP = ipaddress.ip_address("93.184.216.34")  # example.com (documentation IP)
TEST_URL = "https://example.com/api"


# --- database ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_db():
    """Fresh, empty schema for every test (drop + recreate is cheap on SQLite)."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def db(reset_db):
    """A raw SQLAlchemy session for seeding and asserting on stored rows."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(reset_db):
    """TestClient with the lifespan executed (scheduler stays disabled)."""
    with TestClient(app) as test_client:
        yield test_client


# --- DNS (mocked by default; SSRF tests override) ---------------------------

@pytest.fixture(autouse=True)
def mock_dns(monkeypatch):
    """Resolve every hostname to a single public IP.

    Tests that need specific DNS behaviour (private IP, mixed IPs, failure)
    re-patch ``security._resolve_all`` themselves; the later patch wins.
    """

    async def _fake_resolve(hostname):  # noqa: ARG001
        return [PUBLIC_IP]

    monkeypatch.setattr(security, "_resolve_all", _fake_resolve)


# --- TLS cert fetch (stubbed by default) ------------------------------------

@pytest.fixture(autouse=True)
def mock_cert_fetch(monkeypatch):
    """``run_check`` refreshes the TLS cert expiry for https monitors via a
    real socket call; stub it to "unknown" so the mocked-HTTP tests never
    touch the network for certs. SSL tests re-patch
    ``monitoring_service.fetch_cert_expiry`` themselves; the later patch wins.
    """

    def _no_cert(hostname, port=443, timeout=10):  # noqa: ARG001
        return None

    monkeypatch.setattr(monitoring_service, "fetch_cert_expiry", _no_cert)


# --- monitor helpers --------------------------------------------------------

def monitor_payload(**overrides) -> dict:
    """A valid POST /api/monitors body."""
    payload = {
        "name": "Example API",
        "url": TEST_URL,
        "method": "GET",
        "timeout_seconds": 10,
        "interval_seconds": 300,
        "expected_status_codes": [200],
        "expected_fields": [],
        "check_zero_records": False,
        "latency_threshold_ms": 3000,
        "max_response_size_bytes": 1048576,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def make_monitor(db):
    """Factory that inserts a Monitor row directly and returns it."""

    def _make(**overrides) -> Monitor:
        data = {
            "name": "Example API",
            "url": TEST_URL,
            "method": "GET",
            "timeout_seconds": 10,
            "interval_seconds": 300,
            "expected_status_codes": [200],
            "expected_fields": [],
            "check_zero_records": False,
            "latency_threshold_ms": 3000,
            "max_response_size_bytes": 1048576,
            "is_active": True,
        }
        data.update(overrides)
        monitor = Monitor(**data)
        db.add(monitor)
        db.commit()
        db.refresh(monitor)
        return monitor

    return _make


@pytest.fixture()
def create_monitor_via_api(client):
    """Factory that creates a monitor through POST /api/monitors."""

    def _create(**overrides) -> dict:
        response = client.post("/api/monitors", json=monitor_payload(**overrides))
        assert response.status_code == 201, response.text
        return response.json()

    return _create


# --- mocked HTTP transport --------------------------------------------------

def mock_client_factory(handler) -> callable:
    """A ``client_factory`` producing httpx clients backed by ``handler``."""

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


def json_response_handler(status: int = 200, payload=None, delay: float = 0.0):
    """MockTransport handler returning a JSON response after an optional delay."""

    async def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        if delay:
            await asyncio.sleep(delay)
        body = [{"id": 1, "title": "hello"}] if payload is None else payload
        return httpx.Response(status, json=body)

    return handler
