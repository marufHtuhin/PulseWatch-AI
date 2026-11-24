# PulseWatch AI — Backend

FastAPI + SQLAlchemy 2.x + Alembic + HTTPX + APScheduler. MySQL-first, with a
SQLite fallback for local testing. The API contract lives at
`../API_CONTRACT.md` — it is the source of truth for endpoints and schemas.

## Quick start

### Linux / macOS

```bash
cd backend
python3 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt
cp .env.example .env   # optional; defaults work out of the box (SQLite)
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Windows (PowerShell)

```powershell
cd backend
py -m venv ..\.venv
..\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # optional; defaults work out of the box (SQLite)
..\.venv\Scripts\alembic upgrade head
..\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API docs: http://127.0.0.1:8000/docs — Health: http://127.0.0.1:8000/health

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pulsewatch.db` | MySQL: `mysql+pymysql://user:pass@host:3306/pulsewatch` |
| `GEMINI_API_KEY` | _(empty)_ | Optional. Without it, alerts use deterministic fallback templates. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model for AI incident explanations. |
| `FRONTEND_URL` | `http://localhost:5173` | CORS origins, comma-separated. |
| `ALLOW_LOCAL_URLS` | `false` | Dev-only: permits checks against loopback/private IPs. Never in production. |
| `MAX_CONCURRENCY` | `10` | Batch check concurrency cap. |
| `MAX_BATCH_SIZE` | `50` | Max monitors per batch request. |
| `MAX_RESPONSE_READ_BYTES` | `10485760` | Hard cap on response bytes read per check. |
| `LOG_LEVEL` | `INFO` | |
| `APP_ENV` | `development` | |
| `PULSEWATCH_TESTING` | `0` | Set to `1` under pytest so the scheduler does not start. |

## Migrations

```bash
alembic upgrade head          # apply all migrations
alembic revision --autogenerate -m "describe change"   # after model changes
alembic downgrade -1          # roll back one migration
```

The initial migration is dialect-agnostic and runs on both MySQL and SQLite.

## How it works

- **Checks**: `POST /api/monitors/{id}/check` (or the scheduler) runs a real
  HTTP request with SSRF protection (DNS resolved at check time, all IPs
  validated, redirects re-validated, max 5 hops). Response bodies are never
  stored — only metadata.
- **Anomalies**: 9 deterministic rules (`app/services/anomaly_service.py`),
  each a separate function. The historical rule needs ≥10 prior checks.
- **Alerts**: deduplicated per (monitor, anomaly type) while open; Gemini is
  called only when a *new* alert is created, and only with metadata.
  Any Gemini failure falls back to deterministic templates.
- **Scheduler**: one APScheduler interval job per active monitor
  (`max_instances=1`, `coalesce=True`). Create/update/toggle/delete
  reschedule immediately.
- **Secret headers** (`Authorization`, `X-Api-Key`, `Api-Key`, `Cookie`,
  `X-Auth-Token`) are stored in the DB but always returned as `"********"`;
  sending `"********"` on update keeps the stored value.

## Proxies & TLS

Outbound checks honour the standard proxy env vars (`HTTPS_PROXY` /
`HTTP_PROXY` / `ALL_PROXY`, `NO_PROXY`) and the standard CA-bundle env vars
(`SSL_CERT_FILE`, `SSL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`) plus the OS trust
store, so the backend works behind TLS-intercepting corporate/egress proxies
without disabling verification. TLS verification is never disabled.

Note: the sandbox used for development resolves public hostnames to CGNAT
(`198.18.0.0/15`) addresses, which the SSRF policy correctly treats as
non-public — live checks there need `ALLOW_LOCAL_URLS=true`. On a normal
network (public DNS) no override is needed.
