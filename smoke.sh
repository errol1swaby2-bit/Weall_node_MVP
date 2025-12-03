#!/usr/bin/env bash
set -euo pipefail
API="http://127.0.0.1:8000"
echo "[1] Health:"; curl -fsS "$API/health" >/dev/null && echo "ok"
echo "[2] Tier1 request (check server log for code):"
curl -fsS -X POST "$API/poh/request-tier1" -H 'content-type: application/json' \
  -d '{"user":"test@example.com","email":"test@example.com"}' | jq .
echo "[3] Now use the emailed/logged code with:"
echo "curl -X POST $API/poh/verify-tier1 -H 'content-type: application/json' -d '{\"user\":\"test@example.com\",\"code\":\"<CODE>\"}'"
