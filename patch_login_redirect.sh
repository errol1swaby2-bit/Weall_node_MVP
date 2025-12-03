#!/bin/bash

set -e

TARGET="weall_node/frontend/login.html"

if [ ! -f "$TARGET" ]; then
  echo "ERROR: $TARGET not found."
  exit 1
fi

echo "[PATCH] Updating login redirect line in $TARGET ..."

python - << 'PY'
from pathlib import Path

target = Path("weall_node/frontend/login.html")
text = target.read_text()

old_snippet = "const next = sp.get('next') || '/';"
new_snippet = "const next = sp.get('next') || '/frontend/index.html';"

if old_snippet not in text:
    # Fallback: patch any line that contains "const next = sp.get('next')"
    lines = text.splitlines()
    changed = False
    for i, line in enumerate(lines):
        if "const next = sp.get('next')" in line:
            lines[i] = "      const next = sp.get('next') || '/frontend/index.html';"
            changed = True
    if not changed:
        print("Pattern not found, no changes made.")
    else:
        target.write_text("\n".join(lines))
        print("Patched via fallback line replacement.")
else:
    target.write_text(text.replace(old_snippet, new_snippet))
    print("Patched exact snippet.")
PY

echo "[OK] Patch script completed."
