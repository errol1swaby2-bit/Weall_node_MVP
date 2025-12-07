#!/usr/bin/env bash
set -euo pipefail

echo "== WeAll frontend API shim =="

PROJECT_ROOT="$HOME/weall_node"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "-> Using PROJECT_ROOT: $PROJECT_ROOT"
echo "-> Using FRONTEND_DIR: $FRONTEND_DIR"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "WARNING: frontend directory not found at $FRONTEND_DIR"
  echo "Nothing to do, exiting."
  exit 0
fi

cd "$FRONTEND_DIR"

# If in future we need to patch API_BASE or similar, we can do it here.
echo "-> No frontend rewrites required for this setup. Shim is a no-op for now."

echo "== Frontend shim complete =="
