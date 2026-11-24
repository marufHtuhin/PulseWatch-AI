# PulseWatch AI

API monitoring with anomaly detection and alerting. Add any HTTP endpoint
as a monitor and PulseWatch checks it on a schedule, records every check,
detects problems with 11 deterministic anomaly rules, and explains each
incident in plain language — with optional Gemini AI explanations, and
deterministic fallback explanations when no AI key is configured.

No API key is required to run it. Monitoring, anomaly detection, alerting,
and the dashboard all work with zero configuration.

## Features

- **Monitors** — any HTTP/HTTPS endpoint (GET/POST/PUT/DELETE), custom
  headers (secret values masked), request bodies, timeout, check interval
  (30s–30min), expected status codes, expected JSON fields, zero-record
  detection, latency threshold, and max response size.
- **Real checks** — every check is a genuine HTTP request with timing,
  status, size, JSON validity, and record-count metadata. Response bodies
  are never stored.
- **11 deterministic anomaly rules** — high response time (3 severity
  tiers), HTTP errors, timeouts, network errors, zero records, invalid
  JSON, missing fields, oversized responses, unexpected status,
  historical deviation from a rolling baseline (needs ≥10 prior checks),
  and TLS certificate expiry (3 severity tiers by days remaining).
- **Alerts** — deduplicated per (monitor, anomaly type) while open:
  a recurring problem bumps `occurrence_count` instead of creating new
  alerts. Acknowledge / resolve lifecycle with a resolved-alert history.
- **Consecutive-failure alerting** — a new alert is created only after
  a configurable number of consecutive failed checks (1–5, default 2),
  so a single blip does not page you. Anomalies are still recorded on
  every failed check, dedup bumps are unaffected, and a successful check
  resets the counter.
- **Telegram notifications** — new alerts at or above a configurable
  minimum severity are sent to a Telegram chat, plus a recovery message
  when a monitor comes back up. Dedup bumps never re-notify.
- **SSL certificate expiry monitoring** — https monitors have their TLS
  certificate expiry checked (at most once per 24h) and alert before
  the certificate expires.
- **Data retention** — check history and resolved alerts are pruned
  automatically by a daily cleanup job, with configurable retention
  windows and a manual cleanup + preview in Settings.
- **Gemini AI explanations** (optional) — when configured, each new alert
  gets an AI-written title, summary, likely cause, and recommended action
  from metadata only (never response bodies). Any Gemini failure falls
  back to deterministic templates — monitoring never breaks because of AI.
- **Concurrent batch checks** — check up to 50 monitors at once with a
  configurable concurrency cap; partial success is built in (one bad
  monitor never fails the batch).
- **Scheduler** — one APScheduler interval job per active monitor;
  create/update/toggle/delete reschedule immediately.
- **Dashboard** — summary stats (including P50/P95/P99 latency
  percentiles over successful checks in the last 24h), response-time
  trend chart, per-monitor uptime/health (with per-monitor P95), and
  alert lists, auto-refreshing every 30 seconds.
- **SSRF protection** — DNS resolved at check time, every resolved IP
  validated (loopback/private/link-local/reserved/multicast/metadata all
  blocked), redirects re-validated on every hop (max 5).
- **Settings** — persisted defaults for interval, timeout, latency
  threshold, and batch concurrency, plus Telegram notification settings
  and data retention windows.

## Screenshots

Dashboard:

![Dashboard](docs/screenshots/dashboard.png)

Monitors:

![Monitors](docs/screenshots/monitors.png)

Monitor detail:

![Monitor detail](docs/screenshots/monitor-detail.png)

Alerts:

![Alerts](docs/screenshots/alerts.png)

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2 |
| HTTP | httpx (async, with SSRF-safe redirect handling) |
| Scheduler | APScheduler 3.x (AsyncIOScheduler) |
| AI | Google Gemini (`gemini-3.5-flash-lite` by default) — optional |
| Database | MySQL 8 (production) / SQLite (local dev & tests) |
| Frontend | React 18, Vite 6, React Router 6, Tailwind CSS 3, Recharts, Axios |
| Testing | pytest + pytest-asyncio + httpx MockTransport |
| Deployment | Docker / Docker Compose, Render (backend), Vercel (frontend) |

## Architecture

```
┌──────────────┐   HTTP/JSON    ┌──────────────────────────────────┐
│  React SPA   │ ◄────────────► │  FastAPI backend (port 8000)     │
│  (Vite, :5173)  /api/*        │                                  │
└──────────────┘                │  routes: monitors / monitoring / │
                                │  alerts / dashboard / settings   │
                                │                                  │
                                │  services:                       │
                                │   monitoring_service  (pipeline) │
                                │   http_service        (SSRF-safe │
                                │                        real HTTP) │
                                │   anomaly_service     (11 rules) │
                                │   alert_service       (dedup)    │
                                │   ai_service          (Gemini +  │
                                │                        fallback)  │
                                │   dashboard_service   (aggreg.,  │
                                │                        percentiles)│
                                │   notification_service (Telegram)│
                                │   retention_service   (cleanup)  │
                                │   ssl_service         (cert      │
                                │                        expiry)    │
                                │                                  │
                                │  APScheduler: 1 interval job per │
                                │  active monitor + daily 03:00    │
                                │  UTC retention cleanup           │
                                └──────────┬───────────────────────┘
                                           │ SQLAlchemy
                                ┌──────────▼───────────────────────┐
                                │  MySQL 8 (prod) / SQLite (dev)   │
                                │  monitors · monitoring_records · │
                                │  anomalies · alerts · settings   │
                                └──────────────────────────────────┘
```

### How one check works

1. The scheduler (or a manual "Check Now" / batch request) picks a monitor.
2. The URL is validated against the SSRF policy (DNS resolved at check
   time; every IP must be public; redirects re-validated, max 5 hops).
3. A real HTTP request runs with the monitor's method, headers, body, and
   timeout. Only metadata is kept: status, timing, size, content type,
   JSON validity, record count. **The response body is never stored.**
4. For https monitors, the TLS certificate expiry is refreshed (at most
   once per 24h; a failed lookup never fails the check and keeps the
   previously stored expiry).
5. A `MonitoringRecord` is saved and the monitor's `last_*` snapshot
   (status, response time, status code, last checked) is updated, along
   with the consecutive-failure counter (reset to 0 on success,
   incremented on failure).
6. All 11 anomaly rules run against the result; each hit becomes an
   `Anomaly` row.
7. Per anomaly: if an open alert already exists for (monitor, type), its
   `occurrence_count` is bumped; otherwise a new alert is created —
   Gemini content when configured, deterministic template otherwise.
   On a failed check, a new alert is created only once the monitor's
   consecutive-failure threshold (`alert_after_failures`, default 2)
   is reached; dedup bumps and alerts on successful checks are not
   gated.
8. After the check commits, new alerts are sent to Telegram (when
   enabled and severe enough) and a recovery message is sent if the
   monitor just came back up. Notification failures never break
   monitoring.

## Anomaly Rules

| # | Type | Trigger | Severity |
|---|---|---|---|
| 1 | `HIGH_RESPONSE_TIME` | Response time above the monitor's latency threshold | warning (>1x), high (≥2x), critical (≥4x) |
| 2 | `HTTP_ERROR` | Status code ≥ 400 | warning (4xx), high (5xx) |
| 3 | `TIMEOUT` | Request timed out | high |
| 4 | `NETWORK_ERROR` | Could not connect at all (DNS failure, connection refused, SSL error) | high |
| 5 | `ZERO_RECORDS` | Valid response with 0 records, when `check_zero_records` is on | warning |
| 6 | `INVALID_RESPONSE` | Body is not valid JSON when JSON is expected | high |
| 7 | `MISSING_FIELDS` | One or more `expected_fields` absent from the JSON body | warning |
| 8 | `LARGE_RESPONSE` | Response size above `max_response_size_bytes` | warning (<5x), high (≥5x) |
| 9 | `UNEXPECTED_STATUS` | Non-error status outside `expected_status_codes` (e.g. 201 when 200 expected) | warning |
| 10 | `HISTORICAL_ANOMALY` | Latency deviates >2σ from the rolling mean of recent checks | warning (2σ–3σ), high (>3σ) |
| 11 | `SSL_EXPIRING` | TLS certificate expiry within 30 days (https monitors only) | warning (≤30 days), high (≤7 days), critical (expired) |

Rule 10 needs **at least 10 prior checks** before it can fire, so a new
monitor never produces false positives. With zero variance in history, it
only fires on a >2x jump over the mean.

Rule 11 reads the certificate expiry stored on the monitor, refreshed at
most once every 24h. An expired certificate is still detected: its TLS
handshake fails, so no new expiry is fetched, and the stored expiry keeps
aging past its date. Http monitors and monitors with no stored expiry
never produce this finding.

All rules are deterministic: the same check input always yields the same
findings. Each rule is a separate function in
`backend/app/services/anomaly_service.py` and is unit-tested individually.

## AI Integration (Gemini)

- **Optional.** Without `GEMINI_API_KEY`, alerts use deterministic
  fallback templates — one per anomaly type — and everything works.
- **Model** is configurable via `GEMINI_MODEL` (default
  `gemini-3.5-flash-lite`).
- **Called only when a new alert is created** (dedup bumps never call
  the AI), and only with **metadata**: monitor name/method/host, status
  code, timings, anomaly type, and baseline stats. Response bodies are
  never sent to Gemini.
- **Output is strict JSON** validated by Pydantic
  (`title`, `severity`, `summary`, `possible_cause`,
  `recommended_action`). On any failure — no key, network error, quota,
  HTTP error, malformed JSON, wrong schema — the fallback template is
  used and monitoring continues. `ai_generated` on the alert tells you
  which path produced the content.
- Get a free key at [Google AI Studio](https://aistudio.google.com/)
  and set `GEMINI_API_KEY` in `backend/.env`.

## Telegram notifications

Alerts can be delivered to a Telegram chat. Setup:

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the
   bot token it gives you.
2. Message your bot once (any text) so Telegram creates the chat.
3. Get your chat ID by opening
   `https://api.telegram.org/bot<your-bot-token>/getUpdates` in a browser
   and reading the `chat.id` value from the result.
4. In PulseWatch, open **Settings → Telegram notifications**, paste the
   bot token and chat ID, choose a minimum severity, and enable
   notifications. Use **Send test notification** to verify delivery
   (the test works even before enabling).

Credentials can also be set via the `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` environment variables; values saved in Settings win
over the env vars. The bot token is never returned by the API and is
never logged.

Behaviour: only **new** alerts at or above the configured minimum
severity (warning / high / critical, default high) send a notification;
dedup bumps (occurrence-count increases) do not re-notify. A recovery
message is sent when a monitor that was down comes back up with an open
alert. If Telegram is unreachable, the failure is logged and monitoring
continues — notifications never break checks.

## Data retention

Check history does not grow forever. A daily cleanup job runs at
03:00 UTC and deletes:

- `monitoring_records` (and their anomalies) older than the check-history
  retention window — default **90 days** (configurable 7–365).
- `resolved` alerts older than the resolved-alert retention window —
  default **365 days** (configurable 30–1095).

Active and acknowledged alerts are never deleted, however old. Both
windows are configurable in **Settings → Data retention**, which also
shows a preview of what a cleanup would delete and a **Clean up now**
button to run it immediately.

## Database Schema

Five tables, identical on MySQL and SQLite (two dialect-agnostic Alembic
migrations: `0001_initial`, `0002_v3_upgrades`):

| Table | Purpose | Key columns |
|---|---|---|
| `monitors` | Watched endpoints | `id`, `name`, `url`, `method`, `headers` (JSON, secrets stored verbatim — masked at the API boundary), `request_body`, `timeout_seconds`, `interval_seconds`, `expected_status_codes`, `expected_fields`, `check_zero_records`, `latency_threshold_ms`, `max_response_size_bytes`, `alert_after_failures`, `consecutive_failures`, `cert_expires_at`, `cert_checked_at`, `is_active`, `last_status`, `last_response_time_ms`, `last_status_code`, `last_checked_at` |
| `monitoring_records` | One row per check (metadata only) | `id`, `monitor_id` (FK, cascade), `response_time_ms`, `status_code`, `response_size_bytes`, `records_returned`, `is_success`, `error_message`, `checked_at`, `content_type`, `is_valid_json` |
| `anomalies` | One row per rule hit | `id`, `monitor_id` (FK, cascade), `record_id` (FK, cascade), `anomaly_type`, `severity`, `description`, `detected_at` |
| `alerts` | User-facing incidents, deduplicated | `id`, `monitor_id` (FK, cascade), `anomaly_id` (FK, SET NULL), `anomaly_type`, `title`, `severity`, `summary`, `possible_cause`, `recommended_action`, `status` (active/acknowledged/resolved), `ai_generated`, `occurrence_count`, `last_seen_at`, `created_at`, `acknowledged_at`, `resolved_at` |
| `settings` | Single row (id = 1) of user defaults | `default_interval_seconds`, `default_timeout_seconds`, `default_latency_threshold_ms`, `max_concurrency`, `telegram_bot_token`, `telegram_chat_id`, `telegram_enabled`, `telegram_min_severity`, `retention_days`, `alert_retention_days` |

Deleting a monitor cascades to its records, anomalies, and alerts.

## API Overview

Base URL (dev): `http://127.0.0.1:8000`. Full contract:
[`API_CONTRACT.md`](API_CONTRACT.md). Interactive docs at `/docs`.

| Method & Path | Description |
|---|---|
| `GET /` | Root: `{status, project, version}` |
| `GET /health` | Health: `{status, db, scheduler}` |
| `POST /api/monitors` | Create monitor (201) |
| `GET /api/monitors` | List monitors (`search`, `is_active`, `status`, `page`, `page_size`) |
| `GET /api/monitors/{id}` | Get one monitor (404 if missing) |
| `PUT /api/monitors/{id}` | Full update (`"********"` on a secret header keeps the stored value) |
| `PATCH /api/monitors/{id}/toggle` | Pause / resume (flips `is_active`) |
| `DELETE /api/monitors/{id}` | Delete (204, cascades) |
| `POST /api/monitors/{id}/check` | Run one immediate check; returns the record + `anomalies` + `alerts_created` |
| `GET /api/monitoring/history` | Check history (`monitor_id`, `is_success`, `from`, `to`, pagination) |
| `GET /api/monitoring/history/{monitor_id}` | History for one monitor |
| `POST /api/monitoring/batch` | Check up to 50 monitors concurrently; partial success (`succeeded`/`failed` counts, `elapsed_ms`) |
| `GET /api/alerts` | List alerts (`severity`, `status`, `monitor_id`, `search`, pagination) |
| `GET /api/alerts/history` | Resolved alerts only (same filters) |
| `GET /api/alerts/{id}` | Alert detail (includes `monitor`, `anomaly`, `record`) |
| `PATCH /api/alerts/{id}/acknowledge` | active → acknowledged (400 on a resolved alert) |
| `PATCH /api/alerts/{id}/resolve` | → resolved |
| `GET /api/dashboard/summary` | Totals, uptime %, avg response time, 24h check counts, P50/P95/P99 latency |
| `GET /api/dashboard/performance` | Response-time points (`monitor_id`, `hours` ≤ 168; ≤200 points) |
| `GET /api/dashboard/health` | Per-monitor uptime, avg latency, P95 latency, active alerts |
| `GET /api/settings` | Current defaults + Telegram/retention settings + read-only server info |
| `PUT /api/settings` | Update any subset of the settings (token: `"********"` keeps the stored value, `null` clears it) |
| `POST /api/settings/test-notification` | Send a Telegram test message (`{success, detail}`) |
| `POST /api/settings/cleanup` | Run retention cleanup now; returns `{records_deleted, alerts_deleted, anomalies_deleted}` |
| `GET /api/settings/cleanup-preview` | Preview what a cleanup would delete (same shape, no deletion) |

List endpoints return `{items, total, page, page_size}`. Errors use
FastAPI's default `{detail}` shape with proper HTTP status codes.

## Project Structure

```
pulsewatch-ai/
├── API_CONTRACT.md            # Source of truth for endpoints & schemas
├── README.md                  # This file
├── LICENSE                    # MIT license
├── docker-compose.yml         # MySQL 8 + backend (Docker)
├── sample-data/
│   └── sample-monitors.json   # 8 ready-made monitors to try out
├── docs/
│   ├── AI_Prompts.md          # Prompts actually used to build this project
│   ├── AI_Prompts.docx        # Same content as a Word document
│   ├── DEPLOYMENT.md          # Render + Vercel deployment guide
│   └── screenshots/           # UI screenshots used in this README
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   ├── alembic.ini / alembic/ # Migrations (0001_initial, 0002_v3_upgrades)
│   ├── pytest.ini
│   ├── tests/                 # pytest suite (285 tests)
│   └── app/
│       ├── main.py            # FastAPI app + lifespan (scheduler start)
│       ├── api/routes/        # health, monitors, monitoring, alerts,
│       │                      #   dashboard, settings
│       ├── core/              # config, logging, security (SSRF + masking)
│       ├── database/          # engine/session, declarative base
│       ├── models/            # Monitor, MonitoringRecord, Anomaly,
│       │                      #   Alert, AppSettings
│       ├── schemas/           # Pydantic request/response models
│       ├── services/          # monitoring, http, http_client, anomaly,
│       │                      #   alert, ai, dashboard, settings,
│       │                      #   notification (Telegram), retention, ssl
│       ├── scheduler/         # APScheduler jobs (1 per active monitor
│       │                      #   + daily 03:00 UTC retention cleanup)
│       └── utils/             # UTC time helpers
└── frontend/
    ├── package.json           # React 18 + Vite 6 + Tailwind 3
    ├── vite.config.js         # Dev server proxies /api -> :8000
    └── src/
        ├── api/client.js      # One function per endpoint (axios)
        ├── components/        # Sidebar, Cards, Charts, MonitorCard, ...
        ├── hooks/             # useApi (fetch + polling), useToast
        ├── layouts/           # AppLayout (sidebar + topbar)
        ├── pages/             # Dashboard, Monitors, MonitorForm,
        │                      #   MonitorDetail, Alerts, AlertDetail,
        │                      #   Settings, NotFound
        └── utils/format.js    # ms / dates / bytes / uptime formatting
```

## Quick Start

Prerequisites: **Python 3.12+**, **Node.js 18+** (for the frontend), and
— only for the MySQL path — **Docker Desktop** or a local MySQL 8 server.

> **Fastest path:** use the **SQLite quick demo** below. It needs
> nothing but Python and Node — no Docker, no MySQL, no API keys.

### Option A — SQLite quick demo (recommended first run)

**Windows (PowerShell):**

```powershell
# 1. Backend
cd backend
py -m venv ..\.venv
..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # optional; defaults already use SQLite
alembic upgrade head          # create the tables
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 2. Frontend (new terminal, from the project root)
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173
```

**macOS / Linux:**

```bash
cd backend
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# new terminal
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 — the dashboard loads (empty at first).
Backend API docs: http://127.0.0.1:8000/docs.
Health check: http://127.0.0.1:8000/health.

### Option B — MySQL via Docker Compose (production-like)

```powershell
# From the project root. Docker Desktop must be running.
copy backend\.env.example backend\.env
# Edit backend\.env: set DATABASE_URL=mysql+pymysql://pulsewatch:pulsewatchpass@db:3306/pulsewatch
docker compose up --build
```

This starts MySQL 8 (`db`, port 3306) and the backend (`:8000`, runs
migrations automatically). Run the frontend separately with
`npm install && npm run dev` in `frontend/`.

> If you use the `.env` file with Docker Compose, note the compose file
> also sets `DATABASE_URL` in its `environment:` block — the compose
> `environment:` value wins over the `env_file` value for that variable,
> and it already points at the `db` service, so the default works.

### Option C — Local MySQL install (no Docker)

1. Install MySQL 8 and create the database + user:

   ```sql
   CREATE DATABASE pulsewatch CHARACTER SET utf8mb4;
   CREATE USER 'pulsewatch'@'localhost' IDENTIFIED BY 'pulsewatchpass';
   GRANT ALL PRIVILEGES ON pulsewatch.* TO 'pulsewatch'@'localhost';
   FLUSH PRIVILEGES;
   ```

2. In `backend/.env`, set:

   ```
   DATABASE_URL=mysql+pymysql://pulsewatch:pulsewatchpass@127.0.0.1:3306/pulsewatch
   ```

3. Run the backend as in Option A (`alembic upgrade head`, then uvicorn).

| What | Command | URL |
|---|---|---|
| Backend (dev) | `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` (from `backend/`, venv active) | http://127.0.0.1:8000 |
| Frontend (dev) | `npm run dev` (from `frontend/`) | http://127.0.0.1:5173 |
| Frontend (production build) | `npm run build` then `npm run preview` | http://127.0.0.1:4173 |
| Full stack (Docker) | `docker compose up --build` (from project root) | backend :8000 |

The backend serves the API only; the frontend is a separate dev server
(or static build) that talks to it over `/api`.

## Configuration

All backend settings live in `backend/.env` (copy from
`backend/.env.example`). Every variable has a working default.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pulsewatch.db` | MySQL: `mysql+pymysql://user:pass@host:3306/pulsewatch` |
| `GEMINI_API_KEY` | _(empty)_ | Optional. Without it, alerts use deterministic fallback templates. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model for AI incident explanations. |
| `TELEGRAM_BOT_TOKEN` | _(empty)_ | Optional fallback for Telegram notifications. A token saved in Settings wins over this. |
| `TELEGRAM_CHAT_ID` | _(empty)_ | Optional fallback for Telegram notifications. A chat ID saved in Settings wins over this. |
| `FRONTEND_URL` | `http://localhost:5173` | CORS origins, comma-separated. |
| `ALLOW_LOCAL_URLS` | `false` | **Dev-only.** Permits checks against loopback/private IPs. Never `true` in production — the app logs a warning at startup when enabled. |
| `MAX_CONCURRENCY` | `10` | Batch check concurrency cap (also tunable in Settings). |
| `MAX_BATCH_SIZE` | `50` | Max monitors per batch request. |
| `MAX_RESPONSE_READ_BYTES` | `10485760` (10 MB) | Hard cap on response bytes read per check. |
| `LOG_LEVEL` | `INFO` | |
| `APP_ENV` | `development` | Shown read-only in Settings. |
| `PULSEWATCH_TESTING` | `0` | Set to `1` under pytest so the scheduler does not start. |

Frontend: `VITE_API_BASE_URL` (build-time) overrides the API base URL
for the production build; the default is the relative `/api` path, which
the Vite dev server proxies to `http://127.0.0.1:8000`.

## Sample APIs & Testing Scenarios

[`sample-data/sample-monitors.json`](sample-data/sample-monitors.json)
has 8 ready-made monitors. Add them through the UI (**Add Monitor**) or
`POST /api/monitors`. Each one exercises a different behaviour:

| Monitor | What it tests |
|---|---|
| JSONPlaceholder Posts / Users (healthy) | Happy path: 200 JSON, record counting, expected fields |
| httpbin 200 (healthy) | Minimal healthy check |
| httpbin 500 (server error test) | `HTTP_ERROR` (high) + alert creation |
| httpbin 404 (not found test) | `HTTP_ERROR` (warning) |
| httpbin delay 3s (slow API test) | `HIGH_RESPONSE_TIME` (threshold 1000ms) |
| httpbin delay 10s (timeout test) | `TIMEOUT` (timeout 5s) |
| httpbin HTML (invalid JSON test) | `INVALID_RESPONSE` (HTML body, JSON expected) |

Suggested walkthrough: add the healthy Posts monitor, click **Check
Now**, and watch the dashboard fill in. Then add the 500 and delay
monitors, check them, and open **Alerts** — you should see a high
`HTTP_ERROR` alert and a `HIGH_RESPONSE_TIME` alert. Re-check the 500
monitor: the alert's occurrence count goes up instead of creating a
duplicate. Resolve it, check again, and a fresh alert appears.

> Public test APIs can be offline at times — that itself is a useful
> monitoring test (you will see the failure recorded honestly).

## Testing

Backend tests use pytest + pytest-asyncio, run against a throwaway
SQLite database, and mock the network with httpx `MockTransport`
(no live API calls, no Gemini key needed). One test performs a real
check against a local test HTTP server.

```powershell
# From backend/, venv active
pytest tests/ -v
```

**285 tests, all passing** (last run: 24 Nov 2026), covering:

- Health/root payloads; monitor CRUD + validation + filters + pagination
- Secret-header masking (`"********"`, keep-on-update, case-insensitive)
- All 11 anomaly rules individually (incl. severity tiers, the
  ≥10-point historical gate, and the SSL expiry tiers) and the full
  mocked check pipeline
  (healthy, slow, 500/404, timeout, network error, invalid JSON, zero
  records, missing fields, unexpected status, oversized, historical
  deviation, redirects, SSRF-blocked checks)
- Alert creation, dedup (incl. acknowledged alerts), resolve-then-recheck
  creating a new alert, acknowledge/resolve lifecycle + the 400 rule
- Consecutive-failure alerting: new alerts gated until the threshold,
  anomalies still recorded, dedup bumps ungated, counter reset on success
- Telegram notifications: config resolution (DB wins, env fallback),
  severity gating, test notification, recovery messages, send failures
  never breaking monitoring
- SSL monitoring: cert expiry parsing, 24h refresh cadence, expired-cert
  detection from the stored expiry
- Latency percentiles (P50/P95/P99, null when no data, successful checks
  only) in the dashboard summary and per-monitor health
- Retention cleanup: record/anomaly/alert deletion, preview without
  deletion, active alerts never deleted
- Gemini success + all failure modes (HTTP 400, malformed JSON, wrong
  schema, connect error, no key) falling back deterministically
- Batch partial success + a concurrency demonstration (5 × 0.3s checks
  finish well under 1.5s; `max_concurrency=1` takes the sequential ~0.6s)
- Scheduler job registration/rescheduling with a test scheduler instance
- Dashboard aggregations from seeded data (summary, performance incl.
  200-point bucketing, per-monitor health)
- Settings defaults + partial updates
- SSRF helpers (loopback/private/link-local/reserved/multicast/metadata,
  mixed DNS results, DNS failure, `ALLOW_LOCAL_URLS` override)

Test output is written to `backend/logs/pytest.log`.

## Common Errors & Solutions

| Symptom | Cause / Fix |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | Run uvicorn/pytest from the `backend/` directory with the venv active. |
| `alembic upgrade head` fails with a connection error | Check `DATABASE_URL` in `backend/.env`. For MySQL, confirm the server is running and the database/user exist (Option C). For the quick demo, use the default SQLite URL. |
| `Port 8000 already in use` | Another backend is running. Stop it, or use `--port 8001` (and update the Vite proxy target if you do). |
| Frontend shows errors / empty data | The backend must be running on `127.0.0.1:8000`. Start it first, then refresh. The UI shows proper error states with retry — it never shows fake data. |
| Checks fail with "Blocked non-public IP" | The URL resolves to a loopback/private IP. That is the SSRF policy working as designed. For local-dev targets only, set `ALLOW_LOCAL_URLS=true` in `backend/.env` (never in production). |
| Checks fail with "DNS resolution failed" | The hostname does not resolve from the machine running the backend. Verify it with `nslookup <host>`. |
| `npm run dev` fails with missing modules | Run `npm install` in `frontend/` first. Requires Node.js 18+. |
| `pip install -r requirements.txt` fails on Windows | Make sure you use Python 3.12 (`py -3.12 -m venv`) and have a recent pip (`python -m pip install --upgrade pip`). |
| Docker Compose: backend exits, `db` unhealthy | Wait for MySQL to finish first-time init (can take ~30s), then `docker compose up` again. Check `docker compose logs db`. |
| Alerts say `ai_generated: false` | No `GEMINI_API_KEY` is set, or the Gemini call failed — the fallback template was used. This is expected behaviour, not an error. Set a key in `backend/.env` to enable AI explanations. |
| Scheduler jobs not running | The scheduler only starts in the normal app lifespan. Under pytest (`PULSEWATCH_TESTING=1`) it is intentionally disabled; `/health` then reports `"scheduler": "disabled"`. |

## Security

- **SSRF protection** — every check URL is validated at check time:
  only http/https; the hostname is DNS-resolved and **every** resolved IP
  must be public (loopback, private, link-local, reserved, multicast,
  and cloud metadata IPs/hostnames are blocked); redirect targets are
  re-validated on every hop (max 5). `ALLOW_LOCAL_URLS=true` is a
  dev-only override — it still blocks metadata targets — and the app
  logs a warning at startup when enabled.
- **Secrets** — secret headers (`Authorization`, `X-Api-Key`,
  `Api-Key`, `Cookie`, `X-Auth-Token`) are stored in the DB but the API
  only ever returns `"********"`; sending `"********"` on update keeps
  the stored value. URLs in logs are sanitized (no query string,
  fragment, or userinfo). The Gemini API key lives only in `.env`
  (never committed — `.env.example` is the template) and is sent only
  to Google's Generative Language API.
- **Response bodies are never stored** and never sent to Gemini — only
  metadata (status, timings, sizes, anomaly types, baselines).
- **No authentication (yet)** — anyone who can reach the backend can
  use the API. Do not expose the backend publicly without adding auth
  (see Limitations). CORS is restricted to `FRONTEND_URL`.

## Limitations

- **No authentication or multi-user support.** The API is open to
  anyone who can reach it. Fine for local use; not safe to expose
  publicly as-is.
- **MySQL was not verified in this sandbox** (no MySQL server, no
  Docker here). The schema and migration are dialect-agnostic and the
  code paths are identical, but the first real MySQL run should be
  treated as a verification step.
- **No real Gemini key was tested live.** The Gemini integration is
  tested end-to-end with a mocked transport (success + every failure
  mode), but no live call with a real key has been made yet.
- **Not yet deployed.** Render/Vercel deployment is documented in
  [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) but has not been
  performed; free-tier limits (notably Render cold starts) apply.
- **SSRF-blocked checks produce no anomaly or alert by design.** A
  rejected URL is a configuration/policy outcome, not the API going
  down — the check is still recorded as a failed check and the monitor
  is marked down. Genuine connection/DNS failures DO raise a
  `NETWORK_ERROR` anomaly and alert.
- **No alert notifications beyond Telegram** (no email/Slack/webhook)
  — alerts otherwise live in the app only. See Roadmap.
- **Single-process scheduler** — running multiple backend replicas
  would duplicate scheduled checks; the design assumes one instance.

## Roadmap

- Authentication (JWT) + per-user monitors.
- Alert notifications: email, Slack, and generic webhooks (Telegram is
  already implemented).
- Uptime history charts per monitor (30-day view) and status pages.
- Distributed scheduler locking (or a single-worker deployment note)
  for multi-replica setups.
- Frontend tests (Vitest + Testing Library) — the backend has 285
  tests; the frontend currently has none.
- Monitor import/export (bulk JSON) and one-click import of
  `sample-data/sample-monitors.json`.
- Custom check assertions (JSONPath / regex on the response body).
- Dark theme (the UI is light-only today).

## License

MIT — see [LICENSE](LICENSE).
