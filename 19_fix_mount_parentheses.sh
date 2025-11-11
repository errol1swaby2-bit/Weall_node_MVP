#!/usr/bin/env bash
set -euo pipefail
MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "Missing $MAIN"; exit 1; }

cp -f "$MAIN" "$MAIN.bak.$(date +%s)"

# Ensure required imports
grep -q 'from fastapi.staticfiles import StaticFiles' "$MAIN" || \
  sed -i '1i from fastapi.staticfiles import StaticFiles' "$MAIN"
grep -q 'from starlette.responses import RedirectResponse' "$MAIN" || \
  sed -i '1i from starlette.responses import RedirectResponse' "$MAIN"

# Comment out ANY existing /frontend mounts to avoid dupes (and to remove the broken ones)
sed -i -E 's/^(.*app\.mount\(([^"]*"\/frontend"[^)]*)\).*)/# \1  # commented by 19_fix_mount_parentheses.sh/' "$MAIN"

# Rebuild file: insert a single correct mount right AFTER app = FastAPI(...) closes
awk '
  BEGIN {
    in_app=0; depth=0; inserted=0;
  }
  {
    line=$0;
    print line;

    # Detect start of app = FastAPI(
    if (inserted==0 && in_app==0 && line ~ /app[[:space:]]*=[[:space:]]*FastAPI[[:space:]]*\(/) {
      in_app=1;
      # Count parens on this line
      for (i=1; i<=length(line); i++) {
        c=substr(line,i,1);
        if (c=="(") depth++;
        else if (c==")") depth--;
      }
      if (depth==0) {
        print "app.mount(\"/frontend\", StaticFiles(directory=\"weall_node/frontend\", html=True), name=\"frontend\")";
        inserted=1; in_app=0;
      }
      next;
    }

    # While inside the FastAPI(...) block, keep tracking parens
    if (in_app==1) {
      for (i=1; i<=length(line); i++) {
        c=substr(line,i,1);
        if (c=="(") depth++;
        else if (c==")") depth--;
      }
      if (depth==0) {
        # We just closed the FastAPI(...) call; insert the mount now.
        print "app.mount(\"/frontend\", StaticFiles(directory=\"weall_node/frontend\", html=True), name=\"frontend\")";
        inserted=1; in_app=0;
      }
      next;
    }
  }
' "$MAIN" > "$MAIN.tmp" && mv "$MAIN.tmp" "$MAIN"

echo "[✓] Fixed: single /frontend mount placed after app = FastAPI(...)"
