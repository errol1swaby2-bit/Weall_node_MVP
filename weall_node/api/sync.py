#!/usr/bin/env python3
"""
Sync API
------------------------------------
Peer-to-peer synchronization of ledger and node state.
- Provides snapshot pull/push endpoints.
- Allows peer registration and peer list retrieval.
- Tier-3 PoH required for write operations.
"""

import logging, json
from fastapi import APIRouter, HTTPException, Request, Query
from weall_node.weall_runtime.wallet import has_nft
import weall_node.app_state as app_state

router = APIRouter(prefix="/sync", tags=["sync"])
logger = logging.getLogger("sync")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# -------------------------------
# Helpers
# -------------------------------
def _require_tier3(user_id: str):
    """Allow only verified Tier-3 operators."""
    if not has_nft(user_id, "PoH", min_level=3):
        raise HTTPException(status_code=401, detail="PoH Tier-3 NFT required")


# -------------------------------
# Endpoints
# -------------------------------
@router.get("/snapshot")
def get_snapshot():
    """Return the current ledger snapshot."""
    try:
        if not hasattr(app_state, "ledger"):
            raise HTTPException(status_code=500, detail="Ledger unavailable")
        snapshot = app_state.ledger.snapshot()
        size = len(json.dumps(snapshot))
        logger.info("Ledger snapshot served (%d bytes)", size)
        return {"ok": True, "size": size, "snapshot": snapshot}
    except Exception as e:
        logger.exception("Snapshot retrieval failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get snapshot: {e}")


@router.post("/push")
async def push_snapshot(request: Request, user_id: str = Query(...)):
    """
    Receive a snapshot from a peer and merge into local ledger.
    Requires PoH Tier-3 operator NFT.
    """
    _require_tier3(user_id)

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Prevent abuse by limiting snapshot size
    raw = json.dumps(data)
    if len(raw) > 5_000_000:  # ~5MB
        raise HTTPException(status_code=413, detail="Snapshot too large")

    try:
        ledger = app_state.ledger
        ledger.accounts.update(data.get("accounts", {}))

        for pool, members in data.get("pools", {}).items():
            ledger.pools.setdefault(pool, set()).update(members)

        for attr in ("eligibility", "applications", "verifications", "proposals"):
            if hasattr(ledger, attr):
                getattr(ledger, attr).update(data.get(attr, {}))

        if hasattr(ledger, "_save"):
            ledger._save()

        logger.info("Snapshot merged by %s (accounts=%d, pools=%d)", user_id,
                    len(ledger.accounts), len(ledger.pools))
        return {"ok": True, "merged": True, "accounts": len(ledger.accounts)}
    except Exception as e:
        logger.exception("Snapshot merge failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to merge snapshot: {e}")


@router.post("/register_peer")
def register_peer(peer_url: str = Query(...), user_id: str = Query(...)):
    """
    Register a new peer node.
    Requires Tier-3 verification.
    """
    _require_tier3(user_id)

    try:
        peers = app_state.node.register_peer(peer_url)
        logger.info("Peer registered by %s: %s", user_id, peer_url)
        return {"ok": True, "peer_count": len(peers), "peers": peers}
    except Exception as e:
        logger.exception("Peer registration failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/peers")
def list_peers():
    """Return list of known peers."""
    try:
        peers = getattr(app_state.node, "peers", [])
        logger.info("Returned %d known peers", len(peers))
        return {"ok": True, "count": len(peers), "peers": peers}
    except Exception as e:
        logger.exception("Peer list retrieval failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve peers")
