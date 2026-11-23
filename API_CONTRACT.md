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
- `POST /api/monitoring/batch` — body `{ "monitor_ids": [1,2,3] }` (max 50). Runs checks concurrently (bounded), returns `{ "results": [ { "monitor_id": 1, "success": true, "record": {...} | null, "error": null | "..." } ], "succeeded": 2, "failed": 1, "elapsed_ms": 1234 }`. Partial success is required.

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
- `GET /api/settings` -> `{ "default_interval_seconds": 300, "default_timeout_seconds": 10, "default_latency_threshold_ms": 3000, "max_concurrency": 10, "gemini_configured": false, "allow_local_urls": false, "app_env": "development", "telegram_enabled": false, "telegram_min_severity": "high", "telegram_configured": false, "retention_days": 90, "alert_retention_days": 365 }`
- `PUT /api/settings` — body: any subset of the mutable fields. `gemini_configured` / `app_env` are read-only (they come from env config). Persisted in a `settings` table (single row, id = 1).
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

## Gemini AI (backend only)
- Model from env `GEMINI_MODEL` (default `gemini-2.0-flash`). API key from `GEMINI_API_KEY` (optional; app works fully without it).
- Called ONLY when >=1 anomaly is detected for a check. Structured JSON output validated by Pydantic: `{title, severity, summary, possible_cause, recommended_action}`.
- On any Gemini failure (no key, network, quota, invalid JSON): create a deterministic fallback alert from templates. Monitoring never fails because of AI.
- Never send response bodies to Gemini — only metadata (name, method, status, timings, anomaly types, baseline).

## Scheduler
- APScheduler AsyncIOScheduler, single instance in FastAPI lifespan. One interval job per active monitor, `max_instances=1`, `coalesce=True`, `misfire_grace_time` = interval.
- Toggle/create/update/delete of a monitor reschedules immediately. Jobs run the same check pipeline as manual checks.
- A daily retention-cleanup job (`retention_cleanup`) runs at 03:00 UTC and deletes expired records/anomalies and old resolved alerts per the retention settings.
- Scheduler must not start during pytest (guard with env or lifespan test handling).
