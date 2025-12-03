#!/data/data/com.termux/files/usr/bin/bash
set -e

echo "== WeAll starter =="

BASE_DIR="$HOME/weall_node"
VENV_DIR="$BASE_DIR/.venv"
LOG_FILE="$BASE_DIR/api.log"
APP="weall_node.weall_api:app"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

cd "$BASE_DIR"

# Activate venv so uvicorn is available
if [ -d "$VENV_DIR" ]; then
  echo "[venv] activating $VENV_DIR"
  # shellcheck disable=SC1090
  . "$VENV_DIR/bin/activate"
else
  echo "[venv] WARNING: venv not found at $VENV_DIR"
fi

# Try to start IPFS if available
if command -v ipfs >/dev/null 2>&1; then
  if ! pgrep -x ipfs >/dev/null 2>&1; then
    echo "[ipfs] starting daemon..."
    ipfs daemon > "$BASE_DIR/ipfs.log" 2>&1 &
    sleep 5
  else
    echo "[ipfs] ipfs daemon already running"
  fi
else
  echo "[ipfs] ipfs not installed; skipping"
fi

echo "[api] starting uvicorn on http://${HOST}:${PORT}"
python -m uvicorn "$APP" --host "$HOST" --port "$PORT" 2>&1 | tee "$LOG_FILE"
