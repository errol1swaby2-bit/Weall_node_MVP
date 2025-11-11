#!/usr/bin/env bash
set -euo pipefail

API="weall_node.weall_api:app"
HOST="127.0.0.1"
PORT="8000"

echo "== WeAll starter =="

# 1) Start IPFS if not running
if ! pgrep -f "ipfs daemon" >/dev/null 2>&1; then
  echo "[ipfs] starting daemon..."
  nohup ipfs daemon > ipfs.log 2>&1 &
  sleep 2
else
  echo "[ipfs] already running"
fi

# 2) Kill any existing uvicorn serving our app
pkill -f "uvicorn .*${API}" >/dev/null 2>&1 || true

# 3) Launch API (note the `env` here)
echo "[api] starting uvicorn on http://${HOST}:${PORT}"
nohup env PYTHONUNBUFFERED=1 python3 -m uvicorn "${API}" --host "${HOST}" --port "${PORT}" > api.log 2>&1 &

# 4) Quick health/log peek
sleep 1
echo "[api] last 25 log lines:"
tail -n 25 api.log || true

if command -v curl >/dev/null 2>&1; then
  echo "[api] version probe:"
  curl -fsS "http://${HOST}:${PORT}/version" || echo "(version probe failed)"
fi

echo "== Done. Use 'tail -f ~/Weall_node_MVP/api.log' to watch logs =="
