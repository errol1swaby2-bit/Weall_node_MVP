#!/usr/bin/env python3
"""
Pinning API
---------------------------------------------------------
Manages IPFS pinning operations for the WeAll Node.
Requires Tier-2 PoH NFT for write operations.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from weall_node.weall_runtime.storage import get_client
from weall_node.weall_runtime.wallet import has_nft

router = APIRouter(prefix="/pin", tags=["pinning"])
logger = logging.getLogger("pinning")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# -------------------------------
# Models
# -------------------------------
class PinRequest(BaseModel):
    user_id: str = Field(..., description="User requesting pin operation")
    cid: str = Field(..., min_length=10, description="IPFS content identifier")


# -------------------------------
# Helpers
# -------------------------------
def _require_tier2(user_id: str):
    """Allow only Tier-2 verified humans to perform pinning actions."""
    if not has_nft(user_id, "PoH", min_level=2):
        raise HTTPException(status_code=401, detail="PoH Tier-2 NFT required")


def _get_ipfs():
    ipfs = get_client()
    if not ipfs:
        raise HTTPException(status_code=503, detail="IPFS client not ready")
    return ipfs


# -------------------------------
# Routes
# -------------------------------
@router.post("/add")
async def pin_add(req: PinRequest):
    """Pin a CID to the local IPFS node."""
    _require_tier2(req.user_id)
    ipfs = _get_ipfs()
    try:
        result = ipfs.pin_add(req.cid)
        logger.info("CID pinned by %s: %s", req.user_id, req.cid)
        return {"ok": True, "action": "pinned", "cid": req.cid, "result": str(result)}
    except Exception as e:
        logger.exception("Failed to pin CID %s: %s", req.cid, e)
        raise HTTPException(status_code=500, detail=f"Failed to pin CID: {e}")


@router.delete("/remove")
async def pin_remove(
    cid: str = Query(..., description="CID to unpin"),
    user_id: str = Query(..., description="User performing unpin")
):
    """Unpin a CID from the local IPFS node."""
    _require_tier2(user_id)
    ipfs = _get_ipfs()
    try:
        result = ipfs.pin_rm(cid)
        logger.info("CID unpinned by %s: %s", user_id, cid)
        return {"ok": True, "action": "unpinned", "cid": cid, "result": str(result)}
    except Exception as e:
        logger.exception("Failed to unpin CID %s: %s", cid, e)
        raise HTTPException(status_code=500, detail=f"Failed to unpin CID: {e}")


@router.get("/list")
def list_pins():
    """List all pinned objects on the node."""
    ipfs = _get_ipfs()
    try:
        pins = ipfs.pin_ls(type="recursive")
        logger.info("Listed %d pinned items", len(pins))
        return {"ok": True, "count": len(pins), "pins": pins}
    except Exception as e:
        logger.exception("Failed to list pins: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list pins: {e}")
