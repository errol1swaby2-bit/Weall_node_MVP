#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT"
mkdir -p bin

echo "==[04] Ensure /api/health and run both servers =="

# Add a tiny /api/health route if none exists
MAIN_CANDIDATES=("weall_node/main.py" "main.py")
FOUND=""
for p in "${MAIN_CANDIDATES[@]}"; do
  [ -f "$p" ] && FOUND="$p" && break
done
if [ -z "$FOUND" ]; then
  echo "Could not find FastAPI main.py. Aborting."; exit 1
fi

if ! grep -qE '(@app\.get\(|@api\.get\().*?/api/health' "$FOUND"; then
  echo "[*] Adding /api/health to $FOUND"
  cat >> "$FOUND" <<'PY'

# ---- dev-only health endpoint (safe, idempotent) ----
try:
    from fastapi import FastAPI
    app  # noqa: reference check
    @app.get("/api/health")
    def health():
        return {"status":"ok"}
except Exception:
    pass
PY
fi

# Python venv (optional, skip if you already manage envs)
if [ ! -d ".venv" ]; then
  echo "[*] Creating Python venv"
  python3 -m venv .venv
fi
. .venv/bin/activate
pip -q install --upgrade pip wheel >/dev/null
pip -q install fastapi uvicorn[standard] >/dev/null || true

# Start backend
echo "[*] Starting backend (127.0.0.1:8000) ..."
nohup bin/run_api_dev.sh > api.log 2>&1 & echo $! > api.pid
sleep 1

# Frontend deps & start
cd "$ROOT/frontend"
npm install >/dev/null 2>&1 || true
echo "[*] Starting frontend (127.0.0.1:5173) ..."
nohup npm run dev > "$ROOT/frontend.log" 2>&1 & echo $! > "$ROOT/frontend.pid"

echo
echo "[✓] Local dev running"
echo "    Backend: http://127.0.0.1:8000   (logs: $ROOT/api.log)"
echo "    Frontend: http://127.0.0.1:5173  (logs: $ROOT/frontend.log)"
echo
echo "Stop with:  kill \$(cat $ROOT/api.pid $ROOT/frontend.pid) ; rm -f $ROOT/*.pid"
