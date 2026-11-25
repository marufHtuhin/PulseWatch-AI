# PulseWatch AI — API Contract (source of truth)

Backend and frontend MUST build against this contract. Do not change field names
or endpoint paths without coordinator approval.

Base URL (dev): backend on http://127.0.0.1:8000. Frontend dev server proxies
`/api` to the backend (Vite proxy). All responses are JSON.

## Conventions
- IDs are integers. Timestamps are ISO-8601 UTC strings (`created_at`, `updated_at`, `checked_at`, `detected_at`, `acknowledged_at`, `resolved_at`, `last_checked_at`).
- List endpoints return `{ "items": [...], "total": N, "page": P, "page_size": S }` unless noted.
- Errors: FastAPI default `{ "detail": "..." }`, with proper HTTP status codes.
- Enums (lowercase strings unless noted):
  - method: `GET | POST | PUT | DELETE`
  - severity: `info | warning | high | critical`
  - alert status: `active | acknowledged | resolved`
  - anomaly_type: `HIGH_RESPONSE_TIME | HTTP_ERROR | TIMEOUT | NETWORK_ERROR | ZERO_RECORDS | INVALID_RESPONSE | MISSING_FIELDS | LARGE_RESPONSE | UNEXPECTED_STATUS | HISTORICAL_ANOMALY | SSL_EXPIRING`

## Authentication

All `/api/*` endpoints require a Bearer token:
`Authorization: Bearer <access_token>`, except the four public auth
endpoints (`register`, `login`, `forgot-password`,
`reset-password`). `/`, `/health`, and `/docs` stay public.

- `POST /api/auth/register` — body `{ "email": "...", "password": "..." }`
  (valid email, password 8–128 chars). Returns **201** +
  `{ "user": { "id": 1, "email": "...", "created_at": "..." },
  "access_token": "...", "token_type": "bearer" }`. Registration is
  **open**: anyone can create an account. Duplicate email → **400**
  `{ "detail": "Email already registered" }`. Invalid email or a
  password shorter than 8 chars → **422** (Pydantic validation).
- `POST /api/auth/login` — body `{ "email": "...", "password": "..." }`
  (JSON, not form data). Returns **200** +
  `{ "access_token": "...", "token_type": "bearer" }`. Unknown user,
  wrong password, or deactivated account all return **401**
  `{ "detail": "Invalid email or password" }` — one message for every
  failure, so the endpoint cannot enumerate users.
- `GET /api/auth/me` — returns `{ "id": 1, "email": "...",
  "is_admin": false, "created_at": "..." }` for the token's user.
  `is_admin` is `true` only for the admin account (see Admin).
- `POST /api/auth/change-password` — requires a Bearer token. Body
  `{ "current_password": "...", "new_password": "..." }` (new
  password 8–128 chars). Returns **200** +
  `{ "access_token": "...", "token_type": "bearer" }` — a fresh token
  for the current session. Every token issued before the change is
  rejected (401) from then on, so all other sessions are signed out.
  Wrong current password → **401**
  `{ "detail": "Current password is incorrect" }`; the existing
  session is left untouched.
- `POST /api/auth/forgot-password` — body `{ "email": "..." }`.
  Always returns **200** +
  `{ "message": "If an account exists for this email, a reset code
  has been sent." }` — the same message whether or not the email
  exists, so the endpoint cannot enumerate users. For a real account
  it emails a **6-digit code** via Brevo (10-minute expiry); only the
  sha256 hash of the code is stored, never the code itself, and a new
  request invalidates any earlier unused code. At most **3 codes per
  email per hour** — over the cap the response is still the generic
  200, but no code is created or sent. If Brevo is not configured
  (`BREVO_API_KEY` / `EMAIL_FROM` unset) no email is sent, but the
  response is still the generic 200 (a warning is logged
  server-side).
- `POST /api/auth/reset-password` — body `{ "email": "...",
  "otp": "123456", "new_password": "..." }` (otp exactly 6 chars,
  new password 8–128 chars). Returns **200** +
  `{ "message": "Password reset successfully. You can now sign in
  with your new password." }`. A successful reset invalidates all
  tokens issued before it (all sessions must log in again). Every
  failure — unknown email, no live code, expired code, used code, or
  wrong code — returns the same **400**
  `{ "detail": "Invalid or expired reset code." }`. A code locks
  (marked used) after **5 wrong guesses**; a used code cannot be
  submitted twice.
- **Rate limits** (slowapi, per IP — the first `X-Forwarded-For`
  entry, else the client IP): login **5/minute**, register
  **10/hour**, forgot-password **5/hour**, reset-password **10/hour**.
  Over the limit → **429**
  `{ "detail": "Rate limit exceeded. Please try again later." }`.
  `/me` and `/change-password` are not rate-limited: change-password
  is authed, so wrong-current-password attempts are already gated by
  needing a valid session. Limits are in-memory and per instance
  (Redis-backed limiting via slowapi's `storage_uri` is the
  multi-instance upgrade); rate limiting is disabled under pytest.
- Tokens are JWTs (HS256, `sub` = user id), valid for **24 hours**.
  Passwords are bcrypt-hashed; a hash is never returned by any endpoint.
- Missing token → **401** `{ "detail": "Authentication required" }`.
  Invalid, expired, or forged token, or a token for a deleted or
  deactivated user → **401** `{ "detail": "Could not validate
  credentials" }`.
- **Per-user scoping:** every user sees only their own monitors,
  records, alerts, dashboard data, and settings row. Accessing
  another user's object by id returns **404**, not 403 (no existence
  leak). `POST /api/monitoring/batch` silently skips ids the caller
  does not own — they simply do not appear in `results`.

## Admin

The admin is the `ADMIN_EMAIL` account: the startup bootstrap promotes
an existing account with that email to admin (`is_admin: true`) on the
first v4.2 boot, or creates the account as an admin when none exists.
`is_admin` is set **only** by the bootstrap — no endpoint grants or
revokes admin, and registration always creates a normal user
(`is_admin: false`).

Every `/api/admin/*` endpoint requires a Bearer token for an **admin**
user. No token, or an invalid/expired token → **401** (same messages
as Authentication above). A valid token for a non-admin user → **403**
`{ "detail": "Admin access required" }`.

- `GET /api/admin/stats` — platform-wide counts. Returns **200** +
  `{ "total_users": N, "total_monitors": N, "active_monitors": N,
  "total_alerts": N, "active_alerts": N }` (`active_*` = currently
  active monitors / alerts with status `active`).
- `GET /api/admin/users` — every account, oldest first, as a paginated
  list (see Conventions). Each item is
  `{ "id": 1, "email": "...", "is_active": true, "is_admin": false,
  "created_at": "...", "monitor_count": N, "alert_count": N }`.
  Query params: `skip` / `limit` (defaults 0 / 20), `q` (optional
  email substring search). The `page` / `page_size` fields in the
  response envelope are derived from `skip` / `limit`.
- `GET /api/admin/users/{id}` — one user plus their monitors. Returns
  **200** +
  `{ "id": 1, "email": "...", "is_active": true, "is_admin": false,
  "created_at": "...", "monitor_count": N, "alert_count": N,
  "active_alert_count": N, "monitors": [ { "id": 1, "name": "...",
  "url": "...", "is_active": true, "status": "up" } ] }` (`status` is
  the monitor's `last_status`: `up | down | unknown`). Unknown user
  → **404** `{ "detail": "User {id} not found" }`.
- `PATCH /api/admin/users/{id}` — activate/deactivate only. Body
  `{ "is_active": false }`. Returns **200** + the updated user row
  (same shape as one `GET /api/admin/users` item). Deactivating
  blocks the account's login immediately and rejects its existing
  tokens; reactivating restores access. Deactivating yourself →
  **400** `{ "detail": "Admins cannot deactivate themselves" }`;
  changing another admin's status → **400**
  `{ "detail": "Admins cannot change another admin's status" }`.
  Unknown user → **404**. There is no way to change another user's
  password or admin flag here.
- `DELETE /api/admin/users/{id}` — hard-deletes the account and **all**
  of its data: monitors, check records, anomalies, alerts,
  password-reset tokens, and settings. Returns **204** (no body).
  Deleting yourself → **400**
  `{ "detail": "Admins cannot delete themselves" }`; deleting another
  admin → **400**
  `{ "detail": "Admins cannot delete another admin" }`. Unknown user
  → **404**.
- `GET /api/admin/monitors` — read-only list of **every** user's
  monitors, newest first, as a paginated list (see Conventions). Each
  item is `{ "id": 1, "name": "...", "url": "...", "is_active": true,
  "status": "up", "user_id": 1, "owner_email": "..." }` (`status` is
  the monitor's `last_status`). Query params: `skip` / `limit`
  (defaults 0 / 20), `user_id` (optional — only that user's
  monitors). The `page` / `page_size` fields in the response envelope
  are derived from `skip` / `limit`. Ownerless (pre-v4) monitors have
  `user_id` and `owner_email` both `null`.

## Health
- `GET /` -> `{ "status": "ok", "project": "PulseWatch AI", "version": "1.0.0" }`
- `GET /health` -> `{ "status": "ok", "db": "ok", "scheduler": "running" }`

## Monitors
Monitor object:
```json
{
  "id": 1, "name": "JSONPlaceholder Posts",
  "url": "https://jsonplaceholder.typicode.com/posts", "method": "GET",
  "headers": {"Accept": "application/json"}, "request_body": null,
  "timeout_seconds": 10, "interval_seconds": 300,
  "expected_status_codes": [200], "expected_fields": ["id", "title"],
  "check_zero_records": true, "latency_threshold_ms": 3000,
  "max_response_size_bytes": 1048576,
  "alert_after_failures": 2,
  "is_active": true,
  "created_at": "...", "updated_at": "...", "last_checked_at": "...",
  "last_status": "up | down | unknown",
  "last_response_time_ms": 212.5, "last_status_code": 200,
  "consecutive_failures": 0,
  "cert_expires_at": "...", "cert_days_remaining": 41.2
}
```
- `headers`: JSON object of header name -> value. **Secret headers (Authorization, X-Api-Key, Cookie, etc.) are NEVER returned to the frontend** — the API returns `headers` with secret values replaced by `"********"`. On update, `"********"` means "keep existing value".
- `alert_after_failures`: 1–5, default 2. A new alert is created only after this many consecutive failed checks (see "Consecutive-failure alerting" under Alerts).
- `consecutive_failures`: read-only count of the current run of failed checks; resets to 0 on the next successful check.
- `cert_expires_at` / `cert_days_remaining`: TLS certificate expiry for https monitors, refreshed at most once per 24h. `cert_days_remaining` is fractional days (negative when expired); both are `null` for http monitors and when no expiry has been fetched yet.
- `request_body`: string (raw body) or null. Only used for POST/PUT.
- `POST /api/monitors` — body: MonitorCreate (name required, url required + valid http/https, method default GET, timeout_seconds 1-120 default 10, interval_seconds 30/60/300/900/1800 default 300, expected_status_codes default [200], expected_fields default [], check_zero_records default false, latency_threshold_ms default 3000, max_response_size_bytes default 1048576, alert_after_failures 1-5 default 2). Returns 201 + Monitor.
- `GET /api/monitors` — query: `search`, `is_active`, `status` (up/down/unknown), `page` (default 1), `page_size` (default 20, max 100). Returns list envelope.
- `GET /api/monitors/{id}` — 404 if missing.
- `PUT /api/monitors/{id}` — full update (same fields as create).
- `PATCH /api/monitors/{id}/toggle` — flips is_active, returns Monitor. Scheduler reschedules accordingly.
- `DELETE /api/monitors/{id}` — 204, cascades records/anomalies/alerts.
- `POST /api/monitors/{id}/check` — runs one immediate real check, returns the MonitoringRecord (see below) with embedded `anomalies` list and `alerts_created` (list of alert ids).

## Monitoring records
MonitoringRecord object:
```json
{
  "id": 1, "monitor_id": 1, "response_time_ms": 212.5, "status_code": 200,
  "response_size_bytes": 18341, "records_returned": 100, "is_success": true,
  "error_message": null, "checked_at": "...",
  "content_type": "application/json; charset=utf-8", "is_valid_json": true,
  "anomalies": [ { "id": 1, "anomaly_type": "HIGH_RESPONSE_TIME", "severity": "warning", "description": "...", "detected_at": "..." } ]
}
```
- `GET /api/monitoring/history` — query: `monitor_id`, `is_success`, `from`, `to` (ISO datetimes), `page`, `page_size`. Returns list envelope of records (without anomalies embedded, to keep it light).
- `GET /api/monitoring/history/{monitor_id}` — same, scoped to one monitor.
- `POST /api/monitoring/batch` — body `{ "monitor_ids": [1,2,3] }` (max 50). Runs checks concurrently (bounded), returns `{ "results": [ { "monitor_id": 1, "success": true, "record": {...} | null, "error": null | "..." } ], "succeeded": 2, "failed": 1, "elapsed_ms": 1234 }`. Partial success is required. Ids the caller does not own (another user's, or nonexistent) are silently skipped — they do not appear in `results`.

## Alerts
Alert object:
```json
{
  "id": 1, "monitor_id": 1, "monitor_name": "JSONPlaceholder Posts",
  "anomaly_id": 1, "anomaly_type": "HIGH_RESPONSE_TIME",
  "title": "High response time on JSONPlaceholder Posts",
  "severity": "warning", "summary": "...", "possible_cause": "...",
  "recommended_action": "...", "status": "active",
  "ai_generated": true, "occurrence_count": 3, "last_seen_at": "...",
  "created_at": "...", "acknowledged_at": null, "resolved_at": null
}
```
- `GET /api/alerts` — query: `severity`, `status`, `monitor_id`, `search`, `page`, `page_size`. Returns list envelope.
- `GET /api/alerts/{id}` — includes `monitor` (name/url/method) and `anomaly` + `record` (response metrics) objects.
- `PATCH /api/alerts/{id}/acknowledge` — status active -> acknowledged, sets acknowledged_at.
- `PATCH /api/alerts/{id}/resolve` — status -> resolved, sets resolved_at.
- `GET /api/alerts/history` — resolved alerts, same filters as /api/alerts.
- Dedup rule: while an alert for (monitor_id, anomaly_type) is `active` or `acknowledged`, a recurring same-type anomaly does NOT create a new alert — it increments `occurrence_count` and updates `last_seen_at`. A new alert is created only after the previous one is `resolved`.
- Consecutive-failure alerting: on a FAILED check, a new alert is created only once the monitor's `consecutive_failures` reaches `alert_after_failures` (default 2). Anomalies are still recorded on every failed check, and dedup bumps are never gated. Alerts on successful checks (slow response, zero records, ...) are never gated — `consecutive_failures` is 0 on success. A successful check resets `consecutive_failures` to 0.
- `SSL_EXPIRING` anomaly: fires from the stored TLS cert expiry for https monitors. Severity tiers: expired (< 0 days remaining) `critical`, ≤ 7 days `high`, ≤ 30 days `warning`, more than 30 days no finding. No stored expiry (http monitor, or no successful cert fetch yet) means no finding. An expired certificate is still detected: its handshake fails, so no new expiry is fetched, and the stored expiry keeps aging past its date.

## Dashboard
- `GET /api/dashboard/summary` ->
```json
{
  "total_monitors": 5, "active_monitors": 4, "healthy_monitors": 3,
  "unhealthy_monitors": 1, "unknown_monitors": 1,
  "active_alerts": 2, "critical_alerts": 1,
  "overall_uptime_pct": 98.7, "avg_response_time_ms": 342.1,
  "total_checks_24h": 128, "failed_checks_24h": 3,
  "p50_response_time_ms": 198.4, "p95_response_time_ms": 512.0,
  "p99_response_time_ms": 890.5
}
```
- `p50/p95/p99_response_time_ms`: latency percentiles over **successful** checks in the last 24h (linear interpolation; a single value returns itself). `null` when there is no data — never 0.
- `GET /api/dashboard/performance` — query: `monitor_id` (optional), `hours` (default 24, max 168). Returns `{ "points": [ { "time": "...", "monitor_id": 1, "monitor_name": "...", "response_time_ms": 212.5, "status_code": 200, "is_success": true } ] }` (bucketed to at most ~200 points).
- `GET /api/dashboard/health` — returns `{ "monitors": [ { "monitor_id": 1, "name": "...", "status": "up|down|unknown", "uptime_pct": 99.2, "avg_response_time_ms": 210.0, "p95_response_time_ms": 480.3, "last_status_code": 200, "last_checked_at": "...", "active_alerts": 1 } ] }`. `p95_response_time_ms` is the p95 over that monitor's successful checks in the last 24h (`null` when there is no data).

## Settings (extra, for the Settings page)
- `GET /api/settings` -> `{ "default_interval_seconds": 300, "default_timeout_seconds": 10, "default_latency_threshold_ms": 3000, "max_concurrency": 10, "ai_configured": false, "ai_provider": "openrouter", "allow_local_urls": false, "app_env": "development", "telegram_enabled": false, "telegram_min_severity": "high", "telegram_configured": false, "retention_days": 90, "alert_retention_days": 365 }`
- `PUT /api/settings` — body: any subset of the mutable fields. `ai_configured` / `ai_provider` / `app_env` are read-only (they come from env config). Settings are **per-user**: each account has its own row (keyed by `user_id`), so Telegram credentials and retention windows never leak between users.
  - `ai_configured` (bool, read-only): true when the configured AI provider's key is set (`OPENROUTER_API_KEY` by default, `GEMINI_API_KEY` when `AI_PROVIDER=gemini`). `ai_provider` (string, read-only): `"openrouter"` (default) or `"gemini"`.
  - `telegram_enabled` (bool, default false), `telegram_min_severity` (`warning | high | critical`, default `high`).
  - `telegram_configured` (bool, read-only): true when a bot token AND a chat id are available, from the DB or from env (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`). **The token itself is never returned by any response.**
  - `telegram_bot_token` / `telegram_chat_id` (write-only via PUT): send `"********"` for the token to keep the stored value, `null` to clear it (env fallback then applies), or a new value to replace it. DB values win over env vars; env vars are the fallback.
  - `retention_days` (7–365, default 90): check-history retention. `alert_retention_days` (30–1095, default 365): resolved-alert retention.
- `POST /api/settings/test-notification` -> `{ "success": true, "detail": "Test notification sent" }`. Always returns 200; when Telegram is not configured the body reports `{"success": false, "detail": "Telegram not configured"}`. The test ignores the `telegram_enabled` toggle (it verifies credentials before enabling). On a send failure: `{"success": false, "detail": "Failed to send test notification"}`.
- `POST /api/settings/cleanup` — run the retention cleanup immediately. Returns `{ "records_deleted": N, "alerts_deleted": N, "anomalies_deleted": N }`.
- `GET /api/settings/cleanup-preview` — same shape as cleanup, but deletes nothing.
- Retention semantics: cleanup deletes `monitoring_records` (and their anomalies) older than `retention_days`, and `resolved` alerts older than `alert_retention_days` (by `resolved_at`, else `created_at`). Active and acknowledged alerts are never deleted, however old. Alerts pointing at a deleted anomaly get `anomaly_id` set to null.

## Telegram notifications
- New alerts notify Telegram when enabled and the alert severity is at or above `telegram_min_severity` (warning < high < critical). Dedup bumps never notify.
- A recovery message is sent when a check succeeds after the monitor was down and an open alert exists for it.
- Notification failures never break monitoring (sending never raises; failures are logged).

## SSRF protection (backend, must actually work)
- Reject non-http/https URLs.
- Reject hostnames resolving to loopback, private, link-local, reserved, or multicast IPs.
- Reject cloud metadata hostnames/IPs (169.254.169.254, metadata.google.internal).
- Resolve DNS at check time and validate ALL resolved IPs; re-validate after redirects (httpx follow_redirects with a custom check, or manual redirect loop, max 5 redirects).
- Dev-only override: env `ALLOW_LOCAL_URLS=true` permits loopback/private (never in production; log a warning at startup when enabled).

## AI explanations (backend only)
- Default provider is OpenRouter: model from env `OPENROUTER_MODEL` (default `nvidia/nemotron-3.5-lightning:free`), API key from `OPENROUTER_API_KEY` (optional; app works fully without it). Fallback models from env `OPENROUTER_FALLBACK_MODELS` (comma-separated, default `google/gemma-4-26b-a4b-it:free`) are sent as the `models` array — OpenRouter tries them in order if the primary is down or rate-limited. Free models need no credit card and are rate-limited to 20 req/min + 50 req/day (under $10 lifetime credits) / 1,000 req/day ($10+ lifetime credits).
- Provider is selected by env `AI_PROVIDER` (`openrouter` default, `gemini` fallback). Gemini uses `GEMINI_API_KEY` and `GEMINI_MODEL` (default `gemini-3.5-flash-lite`).
- Called ONLY when >=1 anomaly is detected for a check. Structured JSON output validated by Pydantic: `{title, severity, summary, possible_cause, recommended_action}`.
- On any AI failure (no key, network, quota, invalid JSON): create a deterministic fallback alert from templates. Monitoring never fails because of AI.
- Never send response bodies to the AI provider — only metadata (name, method, status, timings, anomaly types, baseline).

## Scheduler
- APScheduler AsyncIOScheduler, single instance in FastAPI lifespan. One interval job per active monitor, `max_instances=1`, `coalesce=True`, `misfire_grace_time` = interval.
- Toggle/create/update/delete of a monitor reschedules immediately. Jobs run the same check pipeline as manual checks.
- A daily retention-cleanup job (`retention_cleanup`) runs at 03:00 UTC and deletes expired records/anomalies and old resolved alerts per each owner's retention settings (ownerless pre-v4 data uses the defaults).
- Scheduler must not start during pytest (guard with env or lifespan test handling).
