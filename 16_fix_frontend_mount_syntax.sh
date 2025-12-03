#!/usr/bin/env bash
set -euo pipefail
MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "Missing $MAIN"; exit 1; }

# 1) Ensure imports exist (idempotent)
grep -q 'from fastapi.staticfiles import StaticFiles' "$MAIN" || \
  sed -i '1i from fastapi.staticfiles import StaticFiles' "$MAIN"
grep -q 'from starlette.responses import RedirectResponse' "$MAIN" || \
  sed -i '1i from starlette.responses import RedirectResponse' "$MAIN"

# 2) Comment out ANY existing /frontend mounts to prevent duplicates
sed -i -E 's/^(.*app\.mount\(([^"]*"\/frontend"[^)]*)\).*)/# \1  # commented by 16_fix_frontend_mount_syntax.sh/' "$MAIN"

# 3) Append a clean, safe mount at the end (after app is fully defined)
if ! grep -q 'normalized frontend mount' "$MAIN"; then
  cat >> "$MAIN" <<'PY'

# --- normalized frontend mount (dev) ---
try:
    app.mount("/frontend", StaticFiles(directory="weall_node/frontend", html=True), name="frontend")
except Exception as _e:
    # If already mounted by other code paths, ignore
    pass
PY
fi

echo "[✓] Fixed mount placement and normalized to weall_node/frontend"
