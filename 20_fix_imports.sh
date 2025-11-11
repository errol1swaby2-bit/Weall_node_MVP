#!/usr/bin/env bash
set -euo pipefail
MAIN="weall_node/main.py"
[ -f "$MAIN" ] || { echo "Missing $MAIN"; exit 1; }
cp -f "$MAIN" "$MAIN.bak.$(date +%s)"

# 1) Remove all existing occurrences of the __future__ import
#    then insert it as the very first line.
grep -q '^from __future__ import annotations' "$MAIN" && \
  sed -i '/^from __future__ import annotations$/d' "$MAIN"
sed -i '1s/^/from __future__ import annotations\n/' "$MAIN"

# 2) Prefer FastAPI’s StaticFiles import; comment Starlette’s duplicate if present
sed -i 's/^from starlette\.staticfiles import StaticFiles/# from starlette.staticfiles import StaticFiles (disabled)/' "$MAIN"

echo "[✓] Imports normalized: __future__ at top, Starlette StaticFiles commented"
