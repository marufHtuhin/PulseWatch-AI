# Deployment Guide — PulseWatch AI

> **Status: not yet deployed.** This guide describes how to deploy
> PulseWatch AI to Render (backend + MySQL) and Vercel (frontend). The
> steps have been written from the project's configuration
> (`docker-compose.yml`, `backend/Dockerfile`, `frontend/vite.config.js`,
> `backend/.env.example`) but have **not** been performed end to end
> yet. Treat the first deployment as a verification run and update
> this guide with anything that differs.

## Overview

| Piece | Service | Notes |
|---|---|---|
| Backend (FastAPI) | Render Web Service (free tier) | Runs Alembic migrations on startup, then uvicorn |
| Database (MySQL 8) | TiDB Cloud (Serverless, free) **or** Railway (free trial) | Backend connects over the public internet; TiDB requires TLS |
| Frontend (React/Vite) | Vercel (free tier) | Static build; API base URL set at build time |

The backend and frontend are deployed independently. The frontend talks
to the backend over HTTPS at the Render URL.

## 1. Database — MySQL

Pick **one** of these. Both give you a MySQL-compatible connection
string of the form
`mysql+pymysql://<user>:<password>@<host>:<port>/<database>`.

### Option A — TiDB Cloud (recommended free option)

1. Create a free account at https://tidbcloud.com/ and create a
   **Serverless** cluster (free tier).
2. Create a database named `pulsewatch` and a SQL user, and note the
   host, port (4000), username, and password.
3. TiDB Serverless **requires TLS**. The backend does **not**
   auto-configure TLS, so on first deploy you must confirm the exact
   connection parameters from TiDB's own docs (typically an `ssl_ca`
   parameter pointing at a CA bundle in the container) and verify the
   connection from the Render logs. If the plain connection string
   fails with a TLS error, that is the expected first thing to fix —
   it is not yet verified for this project.
4. URL-encode special characters in the password when building
   `DATABASE_URL` (e.g. `@` → `%40`).

### Option B — Railway

1. Create a project at https://railway.app/ and add a **MySQL**
   service (free trial credit applies; check current limits).
2. Use the public connection details (host, port, user, password,
   database) from the service's Variables tab.

> **SQLite is not an option in production.** Render's filesystem is
> ephemeral, so a SQLite file would be wiped on every deploy/restart.
> Use MySQL (above) for any deployment.

## 2. Backend — Render Web Service

1. Push this repo to GitHub.
2. In Render (https://render.com/), create a **Web Service** from the
   repo. Render detects the `Dockerfile` in `backend/` — set the
   **Root Directory** to `backend` (or use the Dockerfile path
   `backend/Dockerfile` with the repo root, per Render's Docker setup).
3. **Build Command:** leave default for Docker (Render builds the image
   from the Dockerfile). **Start Command:** the Dockerfile's `CMD`
   already runs `alembic upgrade head && uvicorn app.main:app
   --host 0.0.0.0 --port 8000`; if Render asks for a start command,
   use exactly that.
4. Set the environment variables (Render Dashboard → Environment):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `mysql+pymysql://<user>:<pass>@<host>:<port>/pulsewatch` (from step 1) |
   | `FRONTEND_URL` | Your Vercel URL, e.g. `https://pulsewatch-ai.vercel.app` (comma-separated if several) |
   | `APP_ENV` | `production` |
   | `LOG_LEVEL` | `INFO` |
   | `GEMINI_API_KEY` | (optional) your Gemini key, or leave unset for fallback templates |
   | `GEMINI_MODEL` | `gemini-2.0-flash` |
   | `TELEGRAM_BOT_TOKEN` | (optional) fallback bot token for Telegram notifications; can also be set in the app's Settings UI, which takes precedence |
   | `TELEGRAM_CHAT_ID` | (optional) fallback chat ID for Telegram notifications; can also be set in the app's Settings UI, which takes precedence |
   | `ALLOW_LOCAL_URLS` | `false` (never `true` in production) |
   | `MAX_CONCURRENCY` | `10` |
   | `PULSEWATCH_TESTING` | `0` |

5. Deploy. On first start the container runs `alembic upgrade head`,
   which creates the five tables and applies the `0002_v3_upgrades`
   migration (Telegram settings, consecutive-failure counters, and
   SSL expiry columns) — no extra step is needed.
6. Verify: `https://<your-service>.onrender.com/health` should return
   `{"status": "ok", "db": "ok", "scheduler": "running"}` and
   `https://<your-service>.onrender.com/docs` should show the API docs.

### Render free-tier limits (honest)

- **Cold starts:** free web services spin down after ~15 minutes of
  inactivity; the first request after that takes ~30–60 seconds while
  the service boots. The scheduler also stops while spun down, so
  scheduled checks pause during idle periods.
- **No persistent disk** on the free tier (hence MySQL, not SQLite).
- **750 free instance-hours/month** shared across services.
- **Workaround for cold starts:** a free uptime monitor (e.g.
  UptimeRobot) pinging `/health` every 5 minutes keeps the service
  warm. This is a common, accepted practice on the free tier.

## 3. Frontend — Vercel

1. In Vercel (https://vercel.com/), import the same GitHub repo.
2. Set the **Root Directory** to `frontend`.
3. Framework preset: **Vite**. Build command: `npm run build`.
   Output directory: `dist`.
4. Set the build-time environment variable:

   | Variable | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `https://<your-service>.onrender.com` |

   Without it, the production build calls the relative `/api` path,
   which only works when the frontend is served from the same origin
   as the backend — not the case on Vercel. (The Vite dev server
   proxies `/api` to localhost, so local development needs no
   variable.)
5. Deploy. The site will be live at `https://<project>.vercel.app`.
6. **CORS:** make sure the backend's `FRONTEND_URL` (step 2) matches
   this exact Vercel URL, otherwise the browser will block API calls.
   After changing `FRONTEND_URL` on Render, redeploy the backend (or
   wait for it to restart) for the change to take effect.

## 4. Post-deployment checks

1. `GET /health` on the Render URL → `db: ok`, `scheduler: running`.
2. Open the Vercel site → Dashboard loads (empty state is normal).
3. Add the "JSONPlaceholder Posts" monitor from
   `sample-data/sample-monitors.json`, click **Check Now**, and confirm
   a record appears and the dashboard counts update.
4. Add the "httpbin 500" monitor, check it, and confirm an alert
   appears in **Alerts**.
5. Wait for one scheduled interval (default 5 minutes) and confirm the
   monitor is checked automatically (the `last_checked_at` time
   advances) — this proves the scheduler is running in production.

## 5. Updating a deployment

- **Backend:** push to the connected branch; Render rebuilds and
  redeploys automatically. Migrations run on every container start.
- **Frontend:** push to the connected branch; Vercel rebuilds
  automatically.
- **Breaking schema changes:** create a new Alembic revision
  (`alembic revision --autogenerate -m "..."`) and commit it; the next
  backend deploy applies it. Never edit the existing `0001_initial` or
  `0002_v3_upgrades` migration after it has run against a real database.

## 6. Security notes for production

- `ALLOW_LOCAL_URLS` must stay `false`.
- Keep `GEMINI_API_KEY` in Render's environment variables, never in
  the repo.
- The API currently has **no authentication** — anyone who finds the
  Render URL can use it. Until auth is added, treat the deployment
  URL as semi-private and do not publish it.
- `FRONTEND_URL` should list only your real frontend origin(s).
