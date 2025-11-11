#!/usr/bin/env bash
set -Eeuo pipefail
echo "[13] starting in $(pwd)"
trap 's=$?; echo "[13] error on line ${BASH_LINENO[0]}: ${BASH_COMMAND} (exit $s)"; exit $s' ERR

ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT"
echo "[13] repo: $(pwd)"

# Python env & deps
if [ ! -d ".venv" ]; then
  echo "[13] creating venv"
  python3 -m venv .venv
fi
. .venv/bin/activate
python -V
pip -q install --upgrade pip wheel >/dev/null
pip -q install fastapi uvicorn[standard] starlette >/dev/null
echo "[13] deps ok"

# Ensure env & shims
./11_env_and_api_shim.sh "$ROOT"

# Start API
nohup bin/run_api_dev.sh > api.log 2>&1 & echo $! > api.pid
sleep 1
echo "[13] api pid: $(cat api.pid)"

echo
echo "[✓] Local dev running"
echo "  API:      http://127.0.0.1:8000 (health: /api/health)"
echo "  Frontend: http://127.0.0.1:8000/frontend/index.html"
echo
echo "Tail logs:  tail -f api.log"
echo "Stop:       kill \$(cat api.pid) && rm -f api.pid"
