#!/usr/bin/env bash
set -euo pipefail
MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "Missing $MAIN"; exit 1; }

# Ensure imports
grep -q 'from fastapi.staticfiles import StaticFiles' "$MAIN" || \
  sed -i '1i from fastapi.staticfiles import StaticFiles' "$MAIN"
grep -q 'from starlette.responses import RedirectResponse' "$MAIN" || \
  sed -i '1i from starlette.responses import RedirectResponse' "$MAIN"

# Comment out ANY existing /frontend mounts to avoid duplicates
sed -i -E 's/^(.*app\.mount\(([^"]*"\/frontend"[^)]*)\).*)/# \1  # commented by 15_fix_frontend_mount.sh/' "$MAIN"

# Insert a single correct mount right after app = FastAPI(...)
awk '
  BEGIN{done=0}
  {
    print
    if (!done && $0 ~ /app\s*=\s*FastAPI\s*\(/) {
      print "app.mount(\"/frontend\", StaticFiles(directory=\"weall_node/frontend\", html=True), name=\"frontend\")"
      done=1
    }
  }
' "$MAIN" > "$MAIN.tmp" && mv "$MAIN.tmp" "$MAIN"

echo "[✓] /frontend mount set to weall_node/frontend"
