#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$HOME/Weall_node_MVP}"
cd "$ROOT"

echo "==[01] Env + path normalization =="

# Create root .env (frontend will read .env.* when using import.meta.env)
cat > .env <<'ENV'
VITE_BACKEND_URL=http://127.0.0.1:8000
VITE_CHAIN_RPC=http://127.0.0.1:8545
VITE_CHAIN_ID=1337
VITE_WECOIN_ADDRESS=0x0000000000000000000000000000000000000000
VITE_GOVERNANCE_ADDRESS=0x0000000000000000000000000000000000000000
VITE_POH_ADDRESS=0x0000000000000000000000000000000000000000
ENV

cp .env .env.development 2>/dev/null || true
cp .env .env.local 2>/dev/null || true

# Normalize "/frontendtendtend/" -> "/frontend/" across text files
# Safe: only affects tracked file types (md, html, js, ts, tsx, json)
grep -RIl "/frontendtendtend/" . --include="*.md" --include="*.html" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.json" | while read -r f; do
  sed -i 's#/frontendtendtend/#/frontend/#g' "$f"
  echo "patched: $f"
done

echo "[✓] Env created and paths normalized"
