# PulseWatch AI — Frontend

React 18 + Vite + Tailwind CSS dashboard for the PulseWatch AI API monitoring
platform. Built against `../API_CONTRACT.md` — that file is the source of truth
for every endpoint, schema, enum, and field name.

## Run

```bash
npm install
npm run dev      # http://127.0.0.1:5173 — /api proxied to http://127.0.0.1:8000
npm run build    # production build -> dist/
npm run preview  # serve the production build on http://127.0.0.1:4173
```

The backend must be running on `http://127.0.0.1:8000` for live data. Without it,
every page renders a proper error state with a retry button — the app never
crashes and never shows fake data.

To point the production build at a different backend origin, set
`VITE_API_BASE_URL` at build time (default is the relative `/api` path).

## Pages

| Route | Page |
| --- | --- |
| `/` | Dashboard — summary stats, response-time trend, per-monitor health, recent alerts & activity (auto-refresh 30s) |
| `/monitors` | Monitor list — search, status/active filters, Check Now, pause/resume, edit, delete |
| `/monitors/new` | Add monitor form (also used for edit) |
| `/monitors/:id` | Monitor detail — config, charts, status history, paginated check history, anomalies, alerts |
| `/monitors/:id/edit` | Edit monitor (same form as add) |
| `/alerts` | Alert list — severity/status/monitor filters + search, acknowledge/resolve, history view |
| `/alerts/:id` | Alert detail — AI explanation, metrics at detection, occurrence timeline |
| `/settings` | Monitor defaults (GET/PUT `/api/settings`) + read-only server status |

## Structure

```
src/
  api/client.js        axios instance + one function per endpoint
  components/          Sidebar, Toast, Badges, Cards, Charts, MonitorCard,
                       AlertRow, ConfirmDialog, Controls
  hooks/               useApi (fetch + polling), useToast
  layouts/AppLayout.jsx  sidebar + topbar (live active-alert count) + <Outlet/>
  pages/               Dashboard, Monitors, MonitorForm, MonitorDetail,
                       Alerts, AlertDetail, Settings, NotFound
  utils/format.js      ms / dates / bytes / uptime / anomaly labels
```

## Notes

- Dark theme only, single accent (emerald). No runtime font CDN — system font stack.
- Secret header values are never displayed: the backend returns `"********"`,
  the form shows a masked placeholder, and sending `"********"` back means
  "keep the existing secret".
- All data comes from the backend. No mock data, no random numbers.
- Verification logs live in `logs/` (npm-install, npm-build, npm-dev,
  npm-preview, smoke-test).
