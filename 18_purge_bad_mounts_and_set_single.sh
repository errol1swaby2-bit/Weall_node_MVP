#!/usr/bin/env bash
set -Eeuo pipefail
MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "Missing $MAIN"; exit 1; }
cp -f "$MAIN" "$MAIN.bak.$(date +%s)"

# 1) Ensure imports exist (idempotent)
grep -q 'from fastapi.staticfiles import StaticFiles' "$MAIN" || \
  sed -i '1i from fastapi.staticfiles import StaticFiles' "$MAIN"
grep -q 'from starlette.responses import RedirectResponse' "$MAIN" || \
  sed -i '1i from starlette.responses import RedirectResponse' "$MAIN"

# 2) Comment out ANY existing /frontend mounts to avoid dupes (including our earlier ones)
sed -i -E 's/^(.*app\.mount\(([^"]*"\/frontend"[^)]*)\).*)/# \1  # commented by 18_purge_bad_mounts_and_set_single.sh/' "$MAIN"

# 3) Purge prior injected blocks that may be malformed
#    a) Remove the "normalized frontend mount" blocks we may have added
awk '
  BEGIN {skip=0}
  /normalized frontend mount/ {skip=1; next}
  skip==1 && /^\s*pass\s*$/    {skip=0; next}
  skip==0 {print}
' "$MAIN" > "$MAIN.tmp" && mv "$MAIN.tmp" "$MAIN"

#    b) Remove any @app.on_event("startup") async def _mount_frontend_once() block we added
awk '
  BEGIN {rm=0}
  /^@app\.on_event\("startup"\)/ {rm=1}
  rm==1 && /^\s*def _mount_frontend_once/ {next}
  rm==1 && /^\s*app\.mount\("/ {next}
  rm==1 && /^\s*pass\s*$/ {rm=0; next}
  rm==0 {print}
' "$MAIN" > "$MAIN.tmp" && mv "$MAIN.tmp" "$MAIN"

# 4) Insert one correct mount right after app = FastAPI(...)
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

echo "[✓] Repaired frontend mounts. Backup at: $MAIN.bak.$(date +%s)"
