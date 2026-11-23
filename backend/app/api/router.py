"""Router aggregation: /api/* routers + root (health) router."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import alerts, dashboard, health, monitors, monitoring
from app.api.routes import settings as settings_routes

api_router = APIRouter(prefix="/api")
api_router.include_router(monitors.router)
api_router.include_router(monitoring.router)
api_router.include_router(alerts.router)
api_router.include_router(dashboard.router)
api_router.include_router(settings_routes.router)

root_router = APIRouter()
root_router.include_router(health.router)
