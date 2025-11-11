#!/usr/bin/env bash
set -Eeuo pipefail
echo "[12] starting in $(pwd)"
trap 's=$?; echo "[12] error on line ${BASH_LINENO[0]}: ${BASH_COMMAND} (exit $s)"; exit $s' ERR

ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT"
echo "[12] repo: $(pwd)"

MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "[12] Missing $MAIN"; exit 1; }

# Only add /api/health if missing
if ! grep -qE '(@app\.get\(|@api\.get\().*?/api/health' "$MAIN"; then
  cat >> "$MAIN" <<'PY'

# --- Local dev health endpoint ---
@app.get("/api/health")
def health():
    return {"status": "ok"}
PY
  echo "[12] Added /api/health to $MAIN"
else
  echo "[12] /api/health already present in $MAIN"
fi

# Ensure run script
mkdir -p bin
cat > bin/run_api_dev.sh <<'BASH'
#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
[ -d ".venv" ] && . .venv/bin/activate
PYMOD="weall_node.main:app"
if command -v uvicorn >/dev/null 2>&1; then
  uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --reload
else
  python3 -m uvicorn "$PYMOD" --host 127.0.0.1 --port 8000 --reload
fi
BASH
chmod +x bin/run_api_dev.sh
echo "[12] Wrote bin/run_api_dev.sh"

echo "[12] done"
