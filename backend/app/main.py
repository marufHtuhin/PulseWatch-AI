"""PulseWatch AI — FastAPI application entrypoint.

Lifespan: configure logging, then start the APScheduler (unless TESTING).
Importing this module never starts the scheduler or touches the network.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router, root_router
from app.core.auth import bootstrap_admin
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.database.connection import SessionLocal
from app.scheduler.jobs import shutdown_scheduler, start_scheduler

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    configure_logging(settings.LOG_LEVEL)
    logger.info(
        "PulseWatch AI starting app_env=%s db=%s",
        settings.APP_ENV,
        "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "mysql",
    )
    if settings.ALLOW_LOCAL_URLS:
        logger.warning(
            "SECURITY WARNING: ALLOW_LOCAL_URLS=true — SSRF protection for "
            "loopback/private IPs is DISABLED. Never enable this in production."
        )
    if settings.TESTING:
        logger.info("TESTING mode: scheduler disabled")
    else:
        db = SessionLocal()
        try:
            # Before the scheduler starts: create the admin user (if the
            # ADMIN_* vars are set) and claim pre-v4 ownerless monitors /
            # settings rows for them. No-op when the vars are unset, and
            # never breaks startup (see bootstrap_admin).
            bootstrap_admin(db)
            start_scheduler(db)
        finally:
            db.close()
    yield
    shutdown_scheduler()
    logger.info("PulseWatch AI shut down")


app = FastAPI(
    title="PulseWatch AI",
    version="1.0.0",
    description="Intelligent API Monitoring & Anomaly Alert System",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(root_router)
app.include_router(api_router)
