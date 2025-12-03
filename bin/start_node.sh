#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

LOG_DIR="${PWD}"
SERVER_LOG="${LOG_DIR}/server.log"
IPFS_LOG="${LOG_DIR}/ipfs.log"

# Ensure ipfs is on PATH (Termux default location)
export PATH="$PATH:$PREFIX/bin"

# Initialize IPFS repo if needed
if ! command -v ipfs >/dev/null 2>&1; then
  if [ -x "./go-ipfs/install.sh" ]; then
    echo "[start] Installing go-ipfs..." | tee -a "$IPFS_LOG"
    (cd go-ipfs && bash install.sh) >> "$IPFS_LOG" 2>&1 || true
  fi
fi

if ! command -v ipfs >/dev/null 2>&1; then
  echo "[start] WARNING: ipfs not found; backend will use local fallback." | tee -a "$IPFS_LOG"
else
  if [ ! -d "$HOME/.ipfs" ]; then
    echo "[start] ipfs init..." | tee -a "$IPFS_LOG"
    ipfs init >> "$IPFS_LOG" 2>&1 || true
  fi

  # Start IPFS daemon in background
  echo "[start] ipfs daemon starting..." | tee -a "$IPFS_LOG"
  nohup ipfs daemon >> "$IPFS_LOG" 2>&1 &
  IPFS_PID=$!

  # Wait for API to be up (max ~20s)
  echo "[start] waiting for IPFS API..." | tee -a "$IPFS_LOG"
  for i in $(seq 1 40); do
    if curl -s http://127.0.0.1:5001/api/v0/version >/dev/null 2>&1; then
      echo "[start] IPFS API is up." | tee -a "$IPFS_LOG"
      break
    fi
    sleep 0.5
  done

  # Kill IPFS on exit
  trap 'echo "[start] stopping ipfs ($IPFS_PID)"; kill -TERM $IPFS_PID 2>/dev/null || true' EXIT
fi

# Start the API server
echo "[start] launching WeAll API..." | tee -a "$SERVER_LOG"
exec python3 -m weall_node.main >> "$SERVER_LOG" 2>&1
