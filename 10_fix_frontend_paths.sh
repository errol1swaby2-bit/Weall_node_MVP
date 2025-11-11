#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT"

TARGET_DIR="weall_node/frontend"
echo "==[10] Normalize '/frontendtendtend/' → '/frontend/' in $TARGET_DIR =="
if [ ! -d "$TARGET_DIR" ]; then
  echo "Missing $TARGET_DIR"; exit 1
fi

# Only touch common web files; leave binaries alone
find "$TARGET_DIR" -type f \( -name "*.html" -o -name "*.js" -o -name "*.css" -o -name "*.json" \) \
  -print0 | xargs -0 sed -i 's#/frontendtendtend/#/frontend/#g'

echo "[✓] Path normalization complete."
