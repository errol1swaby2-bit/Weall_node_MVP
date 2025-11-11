#!/usr/bin/env bash
# Verbose, resilient runner with no Rust deps required
set -euo pipefail 2>/dev/null || set -eu
export PYTHONUNBUFFERED=1
export WEALL_DEV_EMAIL=1

cd "$(dirname "$0")/.."
[ -d ".venv" ] && . .venv/bin/activate || true

PYMOD="weall_node.main:app"

echo "[runner] python: $(command -v python3)"
python3 - <<'PY' || true
import sys, importlib
print("[runner] pyver:", sys.version)
try:
    m = importlib.import_module("weall_node.main")
    print("[runner] import weall_node.main OK; has app:", hasattr(m, "app"))
except Exception as e:
    print("[runner] import error:", repr(e))
    raise
PY

# NO --reload to avoid watchfiles/Rust wheels
echo "[runner] starting uvicorn without --reload"
exec python3 -m uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --log-level debug
