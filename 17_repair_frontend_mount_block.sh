#!/usr/bin/env bash
set -euo pipefail
MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "Missing $MAIN"; exit 1; }

# Ensure imports exist
grep -q 'from fastapi.staticfiles import StaticFiles' "$MAIN" || \
  sed -i '1i from fastapi.staticfiles import StaticFiles' "$MAIN"
grep -q 'from starlette.responses import RedirectResponse' "$MAIN" || \
  sed -i '1i from starlette.responses import RedirectResponse' "$MAIN"

# 1) Comment out ANY existing /frontend mounts to avoid duplicates
sed -i -E 's/^(.*app\.mount\(([^"]*"\/frontend"[^)]*)\).*)/# \1  # commented by 17_repair_frontend_mount_block.sh/' "$MAIN"

# 2) Remove the previously added "normalized frontend mount" block if present
#    (delete from marker line to the next line containing only "pass" or end of file)
awk '
  BEGIN { skip=0 }
  /normalized frontend mount/ { skip=1; next }
  skip==1 && /^\s*pass\s*$/    { skip=0; next }
  skip==0 { print }
' "$MAIN" > "$MAIN.tmp" && mv "$MAIN.tmp" "$MAIN"

# 3) Add a safe startup hook that mounts the correct directory once
if ! grep -q '_mount_frontend_once' "$MAIN"; then
  cat >> "$MAIN" <<'PY'

# --- normalized frontend mount via startup hook (dev safe) ---
from fastapi import FastAPI

@app.on_event("startup")
async def _mount_frontend_once() -> None:
    try:
        app.mount("/frontend", StaticFiles(directory="weall_node/frontend", html=True), name="frontend")
    except Exception:
        # Already mounted or running in a path where StaticFiles was set elsewhere
        pass
PY
fi

echo "[✓] Repaired mount block and added startup hook"
