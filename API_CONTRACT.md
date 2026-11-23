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
  - anomaly_type: `HIGH_RESPONSE_TIME | HTTP_ERROR | TIMEOUT | NETWORK_ERROR | ZERO_RECORDS | INVALID_RESPONSE | MISSING_FIELDS | LARGE_RESPONSE | UNEXPECTED_STATUS | HISTORICAL_ANOMALY`

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
  "is_active": true,
  "created_at": "...", "updated_at": "...", "last_checked_at": "...",
  "last_status": "up | down | unknown",
  "last_response_time_ms": 212.5, "last_status_code": 200
}
```
- `headers`: JSON object of header name -> value. **Secret headers (Authorization, X-Api-Key, Cookie, etc.) are NEVER returned to the frontend** — the API returns `headers` with secret values replaced by `"********"`. On update, `"********"` means "keep existing value".
- `request_body`: string (raw body) or null. Only used for POST/PUT.
- `POST /api/monitors` — body: MonitorCreate (name required, url required + valid http/https, method default GET, timeout_seconds 1-120 default 10, interval_seconds 30/60/300/900/1800 default 300, expected_status_codes default [200], expected_fields default [], check_zero_records default false, latency_threshold_ms default 3000, max_response_size_bytes default 1048576). Returns 201 + Monitor.
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

## Dashboard
- `GET /api/dashboard/summary` ->
```json
{
  "total_monitors": 5, "active_monitors": 4, "healthy_monitors": 3,
  "unhealthy_monitors": 1, "unknown_monitors": 1,
  "active_alerts": 2, "critical_alerts": 1,
  "overall_uptime_pct": 98.7, "avg_response_time_ms": 342.1,
  "total_checks_24h": 128, "failed_checks_24h": 3
}
```
- `GET /api/dashboard/performance` — query: `monitor_id` (optional), `hours` (default 24, max 168). Returns `{ "points": [ { "time": "...", "monitor_id": 1, "monitor_name": "...", "response_time_ms": 212.5, "status_code": 200, "is_success": true } ] }` (bucketed to at most ~200 points).
- `GET /api/dashboard/health` — returns `{ "monitors": [ { "monitor_id": 1, "name": "...", "status": "up|down|unknown", "uptime_pct": 99.2, "avg_response_time_ms": 210.0, "last_status_code": 200, "last_checked_at": "...", "active_alerts": 1 } ] }`.

## Settings (extra, for the Settings page)
- `GET /api/settings` -> `{ "default_interval_seconds": 300, "default_timeout_seconds": 10, "default_latency_threshold_ms": 3000, "max_concurrency": 10, "gemini_configured": false, "allow_local_urls": false, "app_env": "development" }`
- `PUT /api/settings` — body: any subset of the defaults above (except gemini_configured/app_env, which are read-only). Persisted in a `settings` table (single row, key-value or columns).

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
- Scheduler must not start during pytest (guard with env or lifespan test handling).
