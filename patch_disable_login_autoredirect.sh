#!/bin/bash

set -e

TARGET="weall_node/frontend/login.html"

if [ ! -f "$TARGET" ]; then
  echo "ERROR: $TARGET not found."
  exit 1
fi

echo "[PATCH] Disabling auto-redirect block in $TARGET ..."

python - << 'PY'
from pathlib import Path

target = Path("weall_node/frontend/login.html")
text = target.read_text()

marker = "// If already logged in and still valid, bounce to next"

if marker not in text:
    print("Marker not found, no changes made.")
else:
    before, rest = text.split(marker, 1)
    end_idx = rest.find("})();")
    if end_idx == -1:
        print("Could not find end of auto-redirect block, no changes made.")
    else:
        after = rest[end_idx + len("})();"):]
        new_text = before + "// AUTO-REDIRECT DISABLED BY PATCH\n" + after
        target.write_text(new_text)
        print("Auto-redirect block removed.")
PY

echo "[OK] Patch script completed."
