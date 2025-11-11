#!/system/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ -d ".venv" ] && . .venv/bin/activate
PYMOD="weall_node.main:app"
if command -v uvicorn >/dev/null 2>&1; then
  exec uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --reload
else
  exec python3 -m uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --reload
fi
