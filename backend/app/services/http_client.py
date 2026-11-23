"""Outbound httpx client construction.

Why not a plain ``httpx.AsyncClient()``? Two reasons:

1. httpx reads proxy config from the environment (``trust_env=True``) and
   crashes on malformed ``no_proxy`` entries — bracketed IPv6 literals like
   ``[::1]`` make its URL parser raise ``Invalid port`` at client
   construction time. (This sandbox's environment contains exactly those.)
2. A monitoring tool's proxy behaviour should be explicit and predictable,
   not an accident of ambient environment variables.

So we parse the proxy env vars ourselves, honour ``no_proxy`` with a small
matcher of our own, and pass an explicit ``proxy=`` with ``trust_env=False``.
The proxy URL (which may contain credentials) is never logged.
"""
from __future__ import annotations

import os
import ssl
from urllib.parse import urlparse

import httpx

_PROXY_ENV_NAMES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


def _proxy_env() -> str | None:
    for name in _PROXY_ENV_NAMES:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _no_proxy_entries() -> list[str]:
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _strip_port(host: str) -> str:
    """Strip a :port suffix from a host, leaving IPv6 literals intact."""
    host = host.strip().lower().strip("[]")
    if ":" in host and host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def host_matches_no_proxy(host: str, entries: list[str]) -> bool:
    host = _strip_port(host)
    for entry in entries:
        candidate = _strip_port(entry)
        if not candidate:
            continue
        if candidate == "*":
            return True
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


def _tls_verify():
    """TLS verification that honours the system trust store.

    httpx's default (certifi's bundle) ignores SSL_CERT_FILE and the OS
    store, so it fails behind TLS-intercepting egress proxies that ship
    their own CA (this sandbox does). A default SSLContext honours
    SSL_CERT_FILE / SSL_CERT_DIR and the OS store instead. Verification
    stays ON — this only changes *which* trust store is used, never
    disables it.
    """
    for env_name in ("SSL_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(env_name)
        if path and os.path.isfile(path):
            return path
    return ssl.create_default_context()


def build_async_client(url: str | None = None, **kwargs) -> httpx.AsyncClient:
    """Build an httpx client with explicit, env-derived proxy config.

    ``url`` (when given) is the target host, used only for ``no_proxy``
    matching — the client itself is not bound to it.
    """
    proxy: str | None = None
    env_proxy = _proxy_env()
    if env_proxy:
        host = urlparse(url).hostname if url else None
        if host is None or not host_matches_no_proxy(host, _no_proxy_entries()):
            proxy = env_proxy
    kwargs.setdefault("verify", _tls_verify())
    return httpx.AsyncClient(proxy=proxy, trust_env=False, **kwargs)
