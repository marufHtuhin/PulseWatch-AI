# Deployment Guide — PulseWatch AI

> **Status: deploy-ready, not yet deployed.** The deploy blockers
> found during prep are fixed in this tree: TiDB TLS is
> auto-configured for `*.tidbcloud.com` hosts (app + Alembic),
> the Dockerfile listens on Render's `$PORT`, a Render Blueprint
> (`render.yaml`) and a Vercel SPA config (`frontend/vercel.json`)
> are included, and the auth migrations (`0003_v4_auth` + `0004_v4_1_auth_ux`,
> password-reset tokens) run
> automatically with the rest. The steps below have **not** been
> performed end to end yet — treat the first deployment as a
> verification run and update this guide with anything that differs.

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
   **Serverless** cluster (free tier). If you already have a TiDB
   account (e.g. for another project), you can reuse the same cluster
   — just create a second database named `pulsewatch` in it.
2. Create a database named `pulsewatch` and a SQL user, and note the
   host, port (4000), username, and password.
3. TiDB Serverless **requires TLS**. The backend auto-configures it:
   any `*.tidbcloud.com` host gets verified TLS via the certifi CA
   bundle (`app/database/connection.py: mysql_ssl_args`, also used by
   Alembic migrations) — just paste the plain connection string, no
   `ssl_ca` parameter needed. Idle pooled connections recycle after
   300s because TiDB closes them after 5 minutes.
4. URL-encode special characters in the password when building
   `DATABASE_URL` (e.g. `@` → `%40`).
5. **Use a user that can CREATE tables.** Alembic runs on every
   Render start and needs the CREATE privilege on the `pulsewatch`
   database. A **Database Read-Write** user can only change data
   (SELECT/INSERT/UPDATE/DELETE) — migrations fail under it with
   `pymysql.err.OperationalError: (1142, "CREATE command denied ...
   for table 'alembic_version'")`. Use the **Database Admin**
   (`role_admin`) user for `DATABASE_URL` instead. For a Starter
   cluster, the documented way to create/repair the admin user is
   the TiDB Cloud CLI: `ti db create-db-sql-users --db-cluster-id
   "<cluster-id>"` (creates `admin`, `read-write` and `read-only`
   users), then use the admin user's connection string. If your
   cluster's console shows **Settings > SQL Users**, you can also
   create/edit a SQL user there with Built-in Role **Database
   Admin**. To check what the current user can do, run `SHOW
   GRANTS;` in the TiDB console SQL Editor — look for CREATE on
   `pulsewatch.*`.

### Option B — Railway

1. Create a project at https://railway.app/ and add a **MySQL**
   service (free trial credit applies; check current limits).
2. Use the public connection details (host, port, user, password,
   database) from the service's Variables tab.

> **SQLite is not an option in production.** Render's filesystem is
> ephemeral, so a SQLite file would be wiped on every deploy/restart.
> Use MySQL (above) for any deployment.

## 2. Backend — Render Web Service

### Option A — Blueprint (recommended)

The repo ships a Render Blueprint (`render.yaml`).

1. Push this repo to GitHub.
2. In Render (https://render.com/), **New → Blueprint**, connect the
   repo, and apply. Render prompts for the three values it cannot fill
   in: `DATABASE_URL` (from §1), `SECRET_KEY` (the JWT signing key —
   generate one with
   `python -c "import secrets; print(secrets.token_hex(32))"`), and
   `FRONTEND_URL` (your Vercel URL from §3 — use a placeholder if the
   frontend is not deployed yet and update it afterwards; Render
   restarts on env changes).
3. Deploy. On first start the container runs `alembic upgrade head`,
   which creates the seven tables and applies the migrations through
   `0004_v4_1_auth_ux` (users table + per-user ownership, password-reset
   tokens) — no extra step
   is needed.
4. **Upgrading a pre-v4 deployment?** If the database already has
   monitors created before auth existed, they are ownerless and
   invisible to every account until claimed. After the deploy, add
   `ADMIN_EMAIL` and `ADMIN_PASSWORD` in the Render Dashboard
   (Environment tab — they are **not** in `render.yaml`, so add them
   by hand), then restart the service: on the next boot the app
   creates that admin account if it does not exist yet and assigns
   all ownerless monitors — plus one ownerless settings row — to it.
   Log in with those credentials to see your existing monitors.

### Option B — Manual Web Service

1. Push this repo to GitHub.
2. In Render (https://render.com/), create a **Web Service** from the
   repo. Render detects the `Dockerfile` in `backend/` — set the
   **Root Directory** to `backend` (or use the Dockerfile path
   `backend/Dockerfile` with the repo root, per Render's Docker setup).
3. **Build Command:** leave default for Docker (Render builds the image
   from the Dockerfile). **Start Command:** the Dockerfile's `CMD`
   already runs `alembic upgrade head && uvicorn app.main:app
   --host 0.0.0.0 --port ${PORT:-8000}`; if Render asks for a start
   command, use exactly that. (Render injects `$PORT` at runtime and
   the service must listen on it — the hardcoded 8000 from earlier
   versions would fail health checks.)
4. Set the environment variables (Render Dashboard → Environment):

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `mysql+pymysql://<user>:<pass>@<host>:<port>/pulsewatch` (from step 1) |
   | `SECRET_KEY` | **Required.** JWT signing key — generate with `python -c "import secrets; print(secrets.token_hex(32))"`. The app refuses to start in production without a real value. |
   | `ADMIN_EMAIL` / `ADMIN_PASSWORD` | (optional) Only needed when upgrading a pre-v4 deployment: on boot, the app creates this admin account and assigns all ownerless monitors + one ownerless settings row to it. Omit for a fresh deployment. |
   | `FRONTEND_URL` | Your Vercel URL, e.g. `https://pulsewatchai.vercel.app` (comma-separated if several; a trailing `/` is tolerated) |
   | `APP_ENV` | `production` |
   | `LOG_LEVEL` | `INFO` |
   | `GEMINI_API_KEY` | (optional) your Gemini key, or leave unset for fallback templates |
   | `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
   | `BREVO_API_KEY` | (optional) Brevo API key for forgot-password emails. The same Brevo account/key as FarmMarket works. Without it (or without `EMAIL_FROM`) the app still runs, but no reset email is sent — the forgot-password endpoint still returns its generic 200. |
   | `EMAIL_FROM` | (optional) Sender address for forgot-password emails. **Must be a sender address verified in the Brevo account** (a verified Gmail address works — no domain needed) or sends fail. |
   | `TELEGRAM_BOT_TOKEN` | (optional) fallback bot token for Telegram notifications; can also be set in the app's Settings UI, which takes precedence |
   | `TELEGRAM_CHAT_ID` | (optional) fallback chat ID for Telegram notifications; can also be set in the app's Settings UI, which takes precedence |
   | `ALLOW_LOCAL_URLS` | `false` (never `true` in production) |
   | `MAX_CONCURRENCY` | `10` |
   | `PULSEWATCH_TESTING` | `0` |

5. Deploy. On first start the container runs `alembic upgrade head`,
   which creates the seven tables and applies the migrations through
   `0004_v4_1_auth_ux` (users table + per-user ownership, password-reset
   tokens) — no extra step
   is needed.
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
   | `VITE_API_BASE_URL` | `https://<your-service>.onrender.com/api` |

   The trailing `/api` is REQUIRED: all backend routes live under
   `/api/*` (e.g. `/api/monitors`). Without it, every frontend API
   call 404s. Without the variable at all, the production build
   calls the relative `/api` path, which only works when the
   frontend is served from the same origin as the backend — not the
   case on Vercel. (The Vite dev server proxies `/api` to localhost,
   so local development needs no variable.)
5. Deploy. The site will be live at `https://<project>.vercel.app`.
   SPA routing (refreshing on `/monitors/1`, deep links) works out of
   the box: `frontend/vercel.json` rewrites all paths to `index.html`.
6. **CORS:** make sure the backend's `FRONTEND_URL` (step 2) matches
   this exact Vercel URL, otherwise the browser will block API calls.
   After changing `FRONTEND_URL` on Render, redeploy the backend (or
   wait for it to restart) for the change to take effect.

## 4. Post-deployment checks

1. `GET /health` on the Render URL → `db: ok`, `scheduler: running`.
2. Open the Vercel site → register an account (registration is open)
   and log in; the Dashboard loads (empty state is normal).
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
  backend deploy applies it. Never edit the existing `0001_initial`,
  `0002_v3_upgrades`, `0003_v4_auth`, or `0004_v4_1_auth_ux` migration after it has run
  against a real database.
- **`CREATE command denied ... for table 'alembic_version'` (seen
  24 Nov 2026):** the `DATABASE_URL` user lacks CREATE on the
  database — auth, TLS and the connection itself are all fine.
  Switch `DATABASE_URL` to the Database Admin user (see §1 step 5)
  and redeploy on Render (Manual Deploy → Deploy latest commit, or
  change the env var, which restarts the service). No code change
  is needed; once the tables exist, a read-write user can run the
  app, but every deploy re-runs Alembic, so keep the admin user in
  `DATABASE_URL` unless you create future tables by hand.

## 6. Security notes for production

- `ALLOW_LOCAL_URLS` must stay `false`.
- Keep `GEMINI_API_KEY` in Render's environment variables, never in
  the repo.
- **Authentication is on, and registration is open.** Anyone who finds
  the frontend URL can create an account and use the app (each account
  sees only its own data). That is the intended v4 behaviour — but be
  aware there is no email verification yet, so do not publish the URL
  more widely than you intend until that lands. Login and the other
  auth endpoints are rate-limited (login 5/minute per IP) since v4.1.
- `SECRET_KEY` must be a strong random value in production (Render
  prompts for it with the Blueprint); the app refuses to start with
  the dev default. Never reuse it across projects, and never commit it.
- `FRONTEND_URL` should list only your real frontend origin(s).
