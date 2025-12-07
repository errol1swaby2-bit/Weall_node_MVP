#!/usr/bin/env bash
set -euo pipefail

echo "== WeAll bootstrap =="
PROJECT_ROOT="$HOME/weall_node"

echo "-> cd to \$PROJECT_ROOT: \$PROJECT_ROOT"
cd "$PROJECT_ROOT"

# 1) Python virtualenv
if [ ! -d ".venv" ]; then
  echo "-> Creating virtualenv (.venv)"
  python -m venv .venv
else
  echo "-> .venv already exists, reusing"
fi

echo "-> Activating virtualenv"
# shellcheck disable=SC1091
. .venv/bin/activate

# 2) Upgrade pip + install Python deps
echo "-> Upgrading pip and installing requirements"
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt
else
  echo "WARNING: requirements.txt not found, skipping"
fi

# 3) Optional: frontend / shim scripts if present
if [ -f "03_frontend_api_shim.sh" ]; then
  echo "-> Running 03_frontend_api_shim.sh"
  chmod +x 03_frontend_api_shim.sh
  bash 03_frontend_api_shim.sh
else
  echo "NOTE: 03_frontend_api_shim.sh not found, skipping"
fi

echo "== Bootstrap complete =="
echo "To start working:  . .venv/bin/activate"
