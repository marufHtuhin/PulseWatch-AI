"""Admin request/response schemas (GET/PATCH/DELETE /api/admin/*).

These are platform-wide views: counts and monitor lists span all users.
Telegram tokens and password hashes are never included in any admin
response.
"""
from __future__ import annotations

from app.schemas.common import APIModel, UtcDateTime


class AdminStatsOut(APIModel):
    """GET /api/admin/stats: platform-wide counts."""

    total_users: int
    total_monitors: int
    active_monitors: int
    total_alerts: int
    active_alerts: int


class AdminUserOut(APIModel):
    """One row of GET /api/admin/users (and the PATCH response)."""

    id: int
    email: str
    is_active: bool
    is_admin: bool
    created_at: UtcDateTime
    monitor_count: int
    alert_count: int


class AdminUserMonitorOut(APIModel):
    """One monitor inside GET /api/admin/users/{user_id}.

    ``status`` is the monitor's ``last_status`` (up | down | unknown).
    """

    id: int
    name: str
    url: str
    is_active: bool
    status: str


class AdminUserDetailOut(APIModel):
    """GET /api/admin/users/{user_id}: user + their monitors."""

    id: int
    email: str
    is_active: bool
    is_admin: bool
    created_at: UtcDateTime
    monitor_count: int
    alert_count: int
    active_alert_count: int
    monitors: list[AdminUserMonitorOut]


class AdminUserUpdate(APIModel):
    """PATCH /api/admin/users/{user_id} body: activate/deactivate only.

    Admins cannot deactivate themselves or change another admin's
    ``is_active`` (see the route); there is no way to grant or revoke
    admin here — only the startup bootstrap sets ``is_admin``.
    """

    is_active: bool


class AdminMonitorOut(APIModel):
    """One row of GET /api/admin/monitors (read-only, all users).

    ``status`` is the monitor's ``last_status`` (up | down | unknown).
    ``user_id`` / ``owner_email`` are None for ownerless monitors.
    """

    id: int
    name: str
    url: str
    is_active: bool
    status: str
    user_id: int | None
    owner_email: str | None
