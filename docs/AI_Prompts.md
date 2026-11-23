# AI Prompts Used to Build PulseWatch AI

This document records the prompts that were actually used during the
construction of PulseWatch AI. It lists each prompt's summary, what it
was used for, what it produced, and whether the output was verified or
modified afterwards. No prompt usage is claimed here beyond what
happened during this build.

> Note on wording: the summaries below describe what each prompt asked
> for and what it produced. They are summaries, not verbatim transcripts
> — the full text of the user's master prompt is not reproduced here.

## 1. User's master prompt + scalability addendum

- **Supplied by:** the project owner (Maruf Hasan)
- **Date:** 23 November 2026
- **Prompt summary:** A full master prompt specifying the PulseWatch AI
  product end to end — an intelligent API monitoring and anomaly alert
  system — plus a later scalability addendum. It defined the product
  concept (monitor any API, detect anomalies, explain incidents with
  AI), the full-stack architecture (FastAPI + SQLAlchemy + MySQL
  backend with a React + Vite frontend), the monitor model (URL,
  method, headers, timeout, interval, expected status codes/fields,
  zero-record checks, latency threshold, response-size limit), the 9
  deterministic anomaly rules, the alert model with deduplication and
  an acknowledge/resolve lifecycle, Gemini AI incident explanations
  with deterministic fallback, concurrent batch checks, an APScheduler
  job per active monitor, SSRF protection, a dashboard (summary,
  performance, per-monitor health), persisted settings, a SQLite
  fallback for local testing, and documentation requirements
  (including this AI-prompts record). The scalability addendum asked
  for the batch/concurrency behaviour to be a demonstrable feature:
  bounded-concurrency batch checks with partial success.
- **What it was used for:** the authoritative specification for the
  whole project. The build was organised around it, and
  `API_CONTRACT.md` was derived from it as the shared source of truth
  for endpoints, schemas, enums, and behaviours.
- **What it produced:** the entire PulseWatch AI system — backend,
  frontend, tests, and docs — as described in the project README.
- **Verified / modified:** the prompt itself was not modified. Its
  requirements were verified in the delivered system: the API contract
  matches the specified endpoints and behaviours, and the automated
  test suite (207 tests) covers the specified rules, flows, and edge
  cases. Two honest gaps are recorded in the README's Limitations:
  MySQL was not verified in the sandbox (no MySQL/Docker available)
  and no live Gemini call with a real key has been made yet.

## 2. Backend build brief

- **Issued to:** a worker agent (Muse) during this build
- **Date:** 23 November 2026
- **Prompt summary:** Build the complete PulseWatch AI backend against
  `API_CONTRACT.md`: FastAPI + SQLAlchemy 2.x + Alembic, MySQL-first
  with a SQLite fallback, all routes (health, monitors, monitoring,
  alerts, dashboard, settings), the real HTTP check pipeline with
  SSRF protection (DNS resolved at check time, all IPs validated,
  redirects re-validated), the 10-rule deterministic anomaly engine,
  alert creation with (monitor, anomaly type) dedup, Gemini AI alert
  content with deterministic fallback templates, concurrent batch
  checks, APScheduler jobs (one per active monitor, rescheduled on
  CRUD), secret-header masking, JSON structured logging, and a
  `docker-compose.yml` for MySQL + backend. The brief also carried
  the sandbox caveats: no MySQL server and no Docker in the build
  environment, and the sandbox's DNS resolving public hostnames to
  CGNAT addresses (so strict-mode live checks are blocked there and
  `ALLOW_LOCAL_URLS=true` is needed for local verification).
- **What it was used for:** producing the backend implementation in
  `backend/`.
- **What it produced:** the full backend — `app/` (routes, services,
  models, schemas, scheduler, security), the Alembic initial
  migration, `requirements.txt`, `.env.example`, `backend/README.md`,
  and `docker-compose.yml` at the project root.
- **Verified / modified:** verified by running it — the backend was
  started with uvicorn, endpoints were exercised, and live checks were
  run with `ALLOW_LOCAL_URLS=true` (logs under `backend/logs/`).
  Later modified once by the tests+docs worker: a multicast SSRF
  bypass found by the test suite (Python's `ip.is_global` is `True`
  for multicast addresses) was fixed in `app/core/security.py` with an
  explicit `is_multicast` check.

## 3. Frontend build brief

- **Issued to:** a worker agent (Muse) during this build
- **Date:** 23 November 2026
- **Prompt summary:** Build the PulseWatch AI frontend against
  `API_CONTRACT.md`: React 18 + Vite + Tailwind CSS, a dark-themed
  dashboard app with pages for Dashboard, Monitors (list/add/edit/
  detail), Alerts (list/detail/history), and Settings, using one API
  client function per endpoint, with auto-refresh, proper error states
  (never fake data), and secret-header values never displayed. The
  Vite dev server proxies `/api` to the backend on port 8000.
- **What it was used for:** producing the frontend implementation in
  `frontend/`.
- **What it produced:** the complete React app — `src/` (pages,
  components, hooks, API client, layouts, utils), `vite.config.js`,
  `tailwind.config.js`, `package.json`, `frontend/README.md`, and a
  production build in `dist/`.
- **Verified / modified:** verified by running it — `npm run build`
  passes and the built app was smoke-tested (logs under
  `frontend/logs/`). Not modified by later workers. The frontend has
  no automated tests yet (recorded as a future improvement in the
  README).

## 4. Tests + docs brief

- **Issued to:** a worker agent (Muse) during this build
- **Date:** 23 November 2026
- **Prompt summary:** Act as the TESTS + DOCS worker for PulseWatch
  AI. Do not rewrite the backend or frontend; fix real bugs exposed by
  tests in place and report them. Part 1: write a meaningful pytest +
  pytest-asyncio + httpx test suite covering health, monitor CRUD and
  validation, secret-header masking, the mocked manual-check pipeline
  (all 9 anomaly scenarios), the anomaly engine unit tests, alert
  creation/dedup/lifecycle, mocked Gemini success and all failure
  modes, batch partial success and a concurrency demonstration,
  scheduler job registration, dashboard aggregations from seeded
  data, settings, and SSRF helpers — running against SQLite with
  `PULSEWATCH_TESTING=1` and mocked DNS/transports (plus one live
  local-server check with `ALLOW_LOCAL_URLS=true`). Part 2: write the
  root README (Windows-first, beginner-friendly), this AI-prompts
  document (+ `.docx`), the backend Dockerfile, and a deployment guide
  (Render + Vercel, with an honest "not yet deployed" disclaimer).
- **What it was used for:** producing the automated test suite and all
  project documentation.
- **What it produced:** `backend/tests/` (11 test modules, 207 tests),
  `backend/pytest.ini`, `backend/logs/pytest.log`, the root
  `README.md`, `docs/AI_Prompts.md`, `docs/AI_Prompts.docx`,
  `backend/Dockerfile`, and `docs/DEPLOYMENT.md`.
- **Verified / modified:** verified by running it — the full suite
  passes (207 passed, 0 failed, on two consecutive runs). The one
  real bug it exposed (the multicast SSRF bypass, above) was fixed in
  the backend and is covered by regression tests. The `.docx` was
  verified by re-reading it with python-docx. The Dockerfile was not
  executed (no Docker in the sandbox); it was checked for syntax and
  consistency with `docker-compose.yml` only. After this worker
  delivered, the build coordinator added a 10th anomaly rule
  (`NETWORK_ERROR`, so connection/DNS failures raise alerts) plus one
  test — the final suite is **209 tests, all passing** (coordinator's
  run: `backend/logs/pytest-coordinator.log`).

## Prompts NOT used

For the record, no prompts beyond the four above were used to build
this project: no prompt was used to generate screenshots (none exist
yet), no prompt was used to produce marketing copy, and no prompt was
used to fabricate test results, deployment status, or live-verification
claims. Anything not verified is labelled as such in the README's
Limitations section.
