"""SSRF protection + secret-header helpers.

DNS is fully mocked here (``security._resolve_all``) so no test depends on
live DNS. IP-literal URLs never touch DNS at all.
"""
from __future__ import annotations

import ipaddress

import pytest

from app.core.security import (
    MASKED_VALUE,
    SSRFBlockedError,
    is_secret_header,
    mask_headers,
    merge_headers,
    validate_url,
)
from app.core import security


def _resolve_to(*ips: str):
    """A fake ``_resolve_all`` returning the given IPs for any hostname."""

    async def _fake(hostname):  # noqa: ARG001
        return [ipaddress.ip_address(ip) for ip in ips]

    return _fake


# --- IP literals: no DNS involved -------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://127.0.0.2:8080/x",
        "http://10.0.0.5/x",
        "http://172.16.0.1/x",
        "http://172.31.255.255/x",
        "http://192.168.1.1/x",
        "http://169.254.1.1/x",  # link-local
        "http://[::1]/x",  # IPv6 loopback
        "http://[fe80::1]/x",  # IPv6 link-local
        "http://224.0.0.1/x",  # multicast (is_global is True for these!)
        "http://[ff02::1]/x",  # IPv6 multicast
        "http://0.0.0.0/x",  # unspecified / reserved
    ],
)
async def test_non_public_ip_literals_are_blocked(url):
    with pytest.raises(SSRFBlockedError, match="non-public"):
        await validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://93.184.216.34/api",
        "http://8.8.8.8/dns",
        "https://1.1.1.1/",
    ],
)
async def test_public_ip_literals_are_allowed(url):
    assert await validate_url(url) == url


# --- metadata ----------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/",
        "http://metadata.google.internal/",
        "http://metadata.google.com/",
        "http://metadata/",
    ],
)
async def test_metadata_targets_are_blocked(url):
    with pytest.raises(SSRFBlockedError, match="[Mm]etadata"):
        await validate_url(url)


# --- schemes / malformed -----------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://example.com/",
        "example.com/no-scheme",
        "https://",  # no hostname
        "",
        "   ",
    ],
)
async def test_non_http_schemes_and_malformed_urls_are_blocked(url):
    with pytest.raises(SSRFBlockedError):
        await validate_url(url)


# --- hostname resolution (mocked DNS) ----------------------------------------

async def test_hostname_resolving_to_public_ip_allowed(monkeypatch):
    monkeypatch.setattr(security, "_resolve_all", _resolve_to("93.184.216.34"))
    assert await validate_url("https://example.com/api") == "https://example.com/api"


async def test_hostname_resolving_to_private_ip_blocked(monkeypatch):
    monkeypatch.setattr(security, "_resolve_all", _resolve_to("10.1.2.3"))
    with pytest.raises(SSRFBlockedError, match="non-public"):
        await validate_url("https://internal.example.com/")


async def test_hostname_with_mixed_ips_blocked_if_any_is_private(monkeypatch):
    # ALL resolved IPs must be public; one private IP blocks the host
    # (this is what stops DNS-rebinding / TOCTOU tricks).
    monkeypatch.setattr(
        security, "_resolve_all", _resolve_to("93.184.216.34", "192.168.0.1")
    )
    with pytest.raises(SSRFBlockedError, match="non-public"):
        await validate_url("https://example.com/")


async def test_dns_failure_blocks_the_check(monkeypatch):
    async def _failing(hostname):  # noqa: ARG001
        raise SSRFBlockedError("DNS resolution failed for host 'example.com'")

    monkeypatch.setattr(security, "_resolve_all", _failing)
    with pytest.raises(SSRFBlockedError, match="DNS resolution failed"):
        await validate_url("https://example.com/")


# --- ALLOW_LOCAL_URLS override ------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
    ],
)
async def test_allow_local_permits_non_public_ips(url):
    assert await validate_url(url, allow_local=True) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
    ],
)
async def test_allow_local_still_blocks_metadata(url):
    with pytest.raises(SSRFBlockedError, match="[Mm]etadata"):
        await validate_url(url, allow_local=True)


async def test_allow_local_permits_hostname_resolving_to_private(monkeypatch):
    monkeypatch.setattr(security, "_resolve_all", _resolve_to("192.168.1.10"))
    assert (
        await validate_url("http://dev.internal/", allow_local=True)
        == "http://dev.internal/"
    )


# --- secret-header helpers -----------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Authorization", True),
        ("AUTHORIZATION", True),
        ("authorization", True),
        ("X-Api-Key", True),
        ("x-api-key", True),
        ("Api-Key", True),
        ("Cookie", True),
        ("X-Auth-Token", True),
        ("Accept", False),
        ("Content-Type", False),
        ("X-Custom-Header", False),
    ],
)
def test_is_secret_header(name, expected):
    assert is_secret_header(name) is expected


def test_mask_headers_replaces_only_secrets():
    masked = mask_headers(
        {"Authorization": "Bearer x", "Accept": "application/json", "X-Api-Key": "k"}
    )
    assert masked == {
        "Authorization": MASKED_VALUE,
        "Accept": "application/json",
        "X-Api-Key": MASKED_VALUE,
    }
    assert mask_headers(None) == {}
    assert mask_headers({}) == {}


def test_merge_headers_masked_value_keeps_stored_secret():
    stored = {"Authorization": "Bearer old", "Accept": "application/json"}
    merged = merge_headers(stored, {"Authorization": "********"})
    assert merged == {"Authorization": "Bearer old"}
    # Full replace: headers absent from the incoming dict are dropped.
    assert "Accept" not in merged


def test_merge_headers_is_case_insensitive_for_stored_secrets():
    stored = {"AUTHORIZATION": "Bearer old"}
    merged = merge_headers(stored, {"Authorization": "********"})
    assert merged == {"Authorization": "Bearer old"}


def test_merge_headers_new_secret_replaces_and_masked_unknown_stays_literal():
    stored = {"Authorization": "Bearer old"}
    assert merge_headers(stored, {"Authorization": "Bearer new"}) == {
        "Authorization": "Bearer new"
    }
    # "********" for a header that was never stored is kept literally —
    # there is nothing to restore.
    assert merge_headers({}, {"Authorization": "********"}) == {
        "Authorization": "********"
    }
    # A non-secret header sent as "********" is just a value.
    assert merge_headers(stored, {"X-Custom": "********"}) == {"X-Custom": "********"}
    assert merge_headers(stored, None) == {}
