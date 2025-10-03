#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-.}"

echo "[weall] Applying production prep files into $ROOT"

mkdir -p "$ROOT/weall-node/api" \
         "$ROOT/weall-node/weall_runtime" \
         "$ROOT/weall-node/p2p" \
         "$ROOT/weall-node/consensus" \
         "$ROOT/weall_export" \
         "$ROOT/sim"

copy() {
  src="$1"
  dst="$2"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  echo "  -> $dst"
}

# Example usage:
# copy "./weall-node/weall_api.py" "$ROOT/weall-node/weall_api.py"

echo "[weall] Done."
