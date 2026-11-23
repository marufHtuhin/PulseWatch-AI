#!/usr/bin/env bash
# PulseWatch AI — coordinator end-to-end integration check.
# Starts the backend on a fresh SQLite DB, exercises the real API flow
# (create monitor -> manual check -> anomaly -> alert -> ack/resolve ->
# dashboard), then checks the frontend dev server + Vite proxy.
# Logs: backend/logs/integration-server.log, backend/logs/integration-checks.log
set -u
ROOT="$HOME/workspace/pulsewatch-ai"
cd "$ROOT/backend" || exit 1
LOG="$ROOT/backend/logs/integration-checks.log"
: > "$LOG"
say() { echo "=== $*" | tee -a "$LOG"; }

# Fresh DB
rm -f pulsewatch.db
ALLOW_LOCAL_URLS=true DATABASE_URL="sqlite:///./pulsewatch.db" \
  "$ROOT/.venv/bin/python" -m alembic upgrade head >> "$LOG" 2>&1
say "migrations applied"

# Start backend (background, durable log)
ALLOW_LOCAL_URLS=true DATABASE_URL="sqlite:///./pulsewatch.db" \
  "$ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  > "$ROOT/backend/logs/integration-server.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null' EXIT

# Wait for health (up to 30s)
for i in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
  sleep 1
done
say "GET /health: $(curl -s --max-time 10 http://127.0.0.1:8000/health)"

# 1. Create a healthy monitor
MON1=$(curl -s --max-time 10 -X POST http://127.0.0.1:8000/api/monitors \
  -H 'Content-Type: application/json' \
  -d '{"name":"JSONPlaceholder Posts","url":"https://jsonplaceholder.typicode.com/posts","method":"GET","interval_seconds":300,"timeout_seconds":10,"expected_status_codes":[200],"expected_fields":["id","title"],"check_zero_records":true,"latency_threshold_ms":3000}')
say "created monitor 1: $MON1"
ID1=$(echo "$MON1" | "$ROOT/.venv/bin/python" -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Manual check (real HTTP)
CHK1=$(curl -s --max-time 30 -X POST "http://127.0.0.1:8000/api/monitors/$ID1/check")
say "manual check 1: $CHK1"

# 3. Create a failing monitor (httpbin 500) + check -> HTTP_ERROR alert
MON2=$(curl -s --max-time 10 -X POST http://127.0.0.1:8000/api/monitors \
  -H 'Content-Type: application/json' \
  -d '{"name":"httpbin 500","url":"https://httpbin.org/status/500","method":"GET","interval_seconds":300,"timeout_seconds":10,"expected_status_codes":[200],"latency_threshold_ms":3000}')
ID2=$(echo "$MON2" | "$ROOT/.venv/bin/python" -c "import sys,json; print(json.load(sys.stdin)['id'])")
CHK2=$(curl -s --max-time 30 -X POST "http://127.0.0.1:8000/api/monitors/$ID2/check")
say "manual check 2 (500): $CHK2"

# 4. Slow monitor (delay 3s, threshold 1000ms) -> HIGH_RESPONSE_TIME
MON3=$(curl -s --max-time 10 -X POST http://127.0.0.1:8000/api/monitors \
  -H 'Content-Type: application/json' \
  -d '{"name":"httpbin slow","url":"https://httpbin.org/delay/3","method":"GET","interval_seconds":300,"timeout_seconds":10,"expected_status_codes":[200],"latency_threshold_ms":1000}')
ID3=$(echo "$MON3" | "$ROOT/.venv/bin/python" -c "import sys,json; print(json.load(sys.stdin)['id'])")
CHK3=$(curl -s --max-time 30 -X POST "http://127.0.0.1:8000/api/monitors/$ID3/check")
say "manual check 3 (slow): $CHK3"

# 5. Alerts list + acknowledge + resolve
say "GET /api/alerts: $(curl -s --max-time 10 'http://127.0.0.1:8000/api/alerts?status=active')"
ALERT_ID=$(curl -s --max-time 10 'http://127.0.0.1:8000/api/alerts?status=active&page_size=1' \
  | "$ROOT/.venv/bin/python" -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")
say "acknowledge alert $ALERT_ID: $(curl -s --max-time 10 -X PATCH "http://127.0.0.1:8000/api/alerts/$ALERT_ID/acknowledge")"
say "resolve alert $ALERT_ID: $(curl -s --max-time 10 -X PATCH "http://127.0.0.1:8000/api/alerts/$ALERT_ID/resolve")"

# 6. Dashboard endpoints (real data)
say "GET /api/dashboard/summary: $(curl -s --max-time 10 http://127.0.0.1:8000/api/dashboard/summary)"
say "GET /api/dashboard/health: $(curl -s --max-time 10 http://127.0.0.1:8000/api/dashboard/health)"
say "GET /api/dashboard/performance: $(curl -s --max-time 10 'http://127.0.0.1:8000/api/dashboard/performance?hours=24' | head -c 600)"
say "GET /api/monitoring/history: $(curl -s --max-time 10 'http://127.0.0.1:8000/api/monitoring/history?page_size=3' | head -c 600)"

# 7. Batch check (partial success: 2 real + 1 missing)
say "POST /api/monitoring/batch: $(curl -s --max-time 30 -X POST http://127.0.0.1:8000/api/monitoring/batch -H 'Content-Type: application/json' -d "{\"monitor_ids\":[$ID1,$ID2,99999]}" | head -c 800)"

# 8. Settings
say "GET /api/settings: $(curl -s --max-time 10 http://127.0.0.1:8000/api/settings)"

# 9. Frontend dev server + Vite proxy (backend must stay up)
cd "$ROOT/frontend" || exit 1
nohup npm run dev -- --host 127.0.0.1 --port 5173 > "$ROOT/frontend/logs/integration-dev.log" 2>&1 &
DEV=$!
for i in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:5173/ >/dev/null 2>&1; then break; fi
  sleep 1
done
say "frontend / (first 300 chars): $(curl -s --max-time 10 http://127.0.0.1:5173/ | head -c 300)"
say "frontend proxy /api/health: $(curl -s --max-time 10 http://127.0.0.1:5173/api/health)"
say "frontend proxy /api/dashboard/summary: $(curl -s --max-time 10 http://127.0.0.1:5173/api/dashboard/summary | head -c 300)"
kill $DEV 2>/dev/null; wait $DEV 2>/dev/null
say "integration script done"
