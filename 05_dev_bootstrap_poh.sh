#!/data/data/com.termux/files/usr/bin/bash
# Dev helper: bootstrap a local user up to PoH Tier 3
# Usage: ./05_dev_bootstrap_poh.sh [email]
# Defaults to errol1swaby2@gmail.com

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
EMAIL="${1:-errol1swaby2@gmail.com}"

echo "== WeAll • Dev PoH bootstrap =="
echo "API_BASE: $API_BASE"
echo "Target user (PoH ID): $EMAIL"
echo

# 0) Make sure we're in the repo root (so this behaves no matter where you run it from)
cd "$(dirname "$0")" || exit 1

echo "-- Step 0: Ensure Tier 1 record exists via /poh/me"
curl -s "$API_BASE/poh/me" \
  -H "X-WeAll-User: $EMAIL" | jq .
echo

# Helper to safely extract request.id (might be null on errors)
extract_req_id () {
  jq -r '.request.id // empty'
}

echo "-- Step 1: Create Tier 2 request"
REQ2="$(
  curl -s -X POST "$API_BASE/poh/requests" \
    -H "Content-Type: application/json" \
    -H "X-WeAll-User: $EMAIL" \
    -d '{
      "target_tier": 2,
      "evidence_cid": null,
      "note": "Dev bootstrap Tier 2 from script"
    }' | extract_req_id
)"

if [ -n "$REQ2" ]; then
  echo "  Tier 2 request id: $REQ2"
  echo "  Approving Tier 2 as jury:local"
  curl -s -X POST "$API_BASE/poh/requests/$REQ2/decision" \
    -H "Content-Type: application/json" \
    -H "X-WeAll-User: jury:local" \
    -d '{
      "decision": "approve",
      "note": "Dev bootstrap Tier 2 approval"
    }' | jq .
else
  echo "  (No Tier 2 request created; you might already be Tier ≥ 2)"
fi
echo

echo "-- Step 2: Create Tier 3 request"
REQ3="$(
  curl -s -X POST "$API_BASE/poh/requests" \
    -H "Content-Type: application/json" \
    -H "X-WeAll-User: $EMAIL" \
    -d '{
      "target_tier": 3,
      "evidence_cid": null,
      "note": "Dev bootstrap Tier 3 from script"
    }' | extract_req_id
)"

if [ -n "$REQ3" ]; then
  echo "  Tier 3 request id: $REQ3"
  echo "  Approving Tier 3 as jury:local"
  curl -s -X POST "$API_BASE/poh/requests/$REQ3/decision" \
    -H "Content-Type: application/json" \
    -H "X-WeAll-User: jury:local" \
    -d '{
      "decision": "approve",
      "note": "Dev bootstrap Tier 3 approval"
    }' | jq .
else
  echo "  (No Tier 3 request created; you might already be Tier ≥ 3)"
fi
echo

echo "-- Step 3: Final /poh/me for sanity"
curl -s "$API_BASE/poh/me" \
  -H "X-WeAll-User: $EMAIL" | jq .
echo
echo "== Dev PoH bootstrap complete =="
