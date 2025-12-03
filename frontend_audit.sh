#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
echo "== WeAll Frontend Wiring Audit =="
echo "Scanning: $ROOT"

echo
echo "-- env keys (.env / .env.*) --"
grep -hRIE '^(VITE_|NEXT_PUBLIC_)' .env* 2>/dev/null || echo "(no .env* keys found)"

echo
echo "-- expected env keys (missing?) --"
expected=(
  VITE_API_BASE
  VITE_CHAIN_RPC
  VITE_CHAIN_ID
  VITE_WECOIN_ADDRESS
  VITE_GOVERNANCE_ADDRESS
  VITE_POH_ADDRESS
  VITE_IPFS_API
  VITE_IPFS_GATEWAY
)
for k in "${expected[@]}"; do
  if ! grep -hRIE "^\s*${k}=" .env* >/dev/null 2>&1; then
    echo "MISSING: $k"
  fi
done

echo
echo "-- blockchain libs used --"
grep -RInE 'ethers|web3|viem|wagmi|window\.ethereum|keplr|cosmos|@solana/web3' "$ROOT" | sed -n '1,200p' || echo "(no chain libs referenced)"

echo
echo "-- contract address usage --"
grep -RInE '(0x[a-fA-F0-9]{40})|WECOIN|GOVERNANCE|POH|contract\(|new Contract\(' "$ROOT" | sed -n '1,200p' || echo "(no obvious contract refs)"

echo
echo "-- signer/provider patterns --"
grep -RInE 'JsonRpcProvider|BrowserProvider|getSigner|new ethers\.providers|createPublicClient' "$ROOT" | sed -n '1,200p' || echo "(no provider/signer found)"

echo
echo "-- API calls (fetch/axios) --"
grep -RInE 'fetch\(|axios\.' "$ROOT" | sed -n '1,200p' || echo "(no API calls found)"

echo
echo "-- IPFS usage --"
grep -RInE 'ipfs|VITE_IPFS' "$ROOT" | sed -n '1,200p' || echo "(no IPFS refs)"

echo
echo "-- router/pages --"
( [ -d src/pages ] && find src/pages -maxdepth 2 -type f -name '*.tsx' -o -name '*.ts' ) 2>/dev/null | sed -n '1,200p' || echo "(no src/pages folder)"
grep -RInE 'react-router|createBrowserRouter|<Link |useNavigate|next/router' src 2>/dev/null | sed -n '1,200p' || true

echo
echo "-- places that still point to dev files (/src/*.ts[x]) --"
grep -RIn '/src/.*\.tsx\|/src/.*\.ts' . | sed -n '1,200p' || echo "(none)"

echo
echo "-- built output sanity (dist/) --"
if [ -f dist/index.html ]; then
  echo "dist/index.html present"
  grep -nE '/assets/.*\.js' dist/index.html | sed -n '1,10p' || true
else
  echo "dist/ is missing (run: npm run build)"
fi

echo
echo "== DONE =="
