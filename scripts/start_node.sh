#!/usr/bin/env bash
set -euo pipefail

# Simple dev/prod bootstrapper for the modular API entrypoint.
# Usage:
#   ./scripts/start_node.sh            # default: 0.0.0.0:8000, reload on
#   PORT=9000 RELOAD=0 ./scripts/start_node.sh

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"

if [[ "${RELOAD}" == "1" ]]; then
  exec uvicorn weall_node.main:app --host "$HOST" --port "$PORT" --reload
else
  exec uvicorn weall_node.main:app --host "$HOST" --port "$PORT"
fi
