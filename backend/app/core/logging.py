"""Structured (JSON) logging. Never log secrets, headers, or API keys."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Keep noisy third-party loggers quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"pulsewatch.{name}")


def sanitize_url(url: str) -> str:
    """Strip query string, fragment, and userinfo so secrets never reach logs."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}{parsed.path}"
    except Exception:
        return "<unparsable-url>"
