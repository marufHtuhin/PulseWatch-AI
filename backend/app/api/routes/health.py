"""Root + health endpoints (no /api prefix)."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.database.connection import SessionLocal
from app.scheduler.jobs import scheduler

router = APIRouter()


@router.api_route("/", methods=["GET", "HEAD"])
def root() -> dict:
    return {"status": "ok", "project": "PulseWatch AI", "version": "1.0.0"}


# HEAD is allowed alongside GET: uptime checkers (e.g. UptimeRobot's free
# plan) probe with HEAD, and a GET-only route answers them with 405.
@router.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict:
    db_status = "ok"
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    finally:
        db.close()
    return {
        "status": "ok" if db_status == "ok" else "error",
        "db": db_status,
        "scheduler": "running" if scheduler.running else "disabled",
    }
