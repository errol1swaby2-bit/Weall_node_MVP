#!/usr/bin/env python3
"""
Disputes API
------------------------------------
Handles content dispute creation and retrieval.
Future versions will sync with on-chain governance.
"""

import logging, time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..weall_executor import executor

router = APIRouter(prefix="/disputes", tags=["disputes"])
logger = logging.getLogger("disputes")

if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

# In-memory MVP state (temporary)
DISPUTES = {}
COUNTER = 1


# -------------------------------
# Pydantic Models
# -------------------------------
class DisputeCreate(BaseModel):
    user_id: str
    post_id: int
    description: str


class DisputeResolve(BaseModel):
    dispute_id: int
    resolver_id: str
    decision: str  # "approve" | "reject"


# -------------------------------
# Routes
# -------------------------------
@router.post("/create")
def create_dispute(req: DisputeCreate):
    """
    Create a new dispute entry.
    Eventually recorded on-chain as a DISPUTE_CREATE transaction.
    """
    global COUNTER
    did = COUNTER
    COUNTER += 1

    tx = {
        "type": "DISPUTE_CREATE",
        "user": req.user_id,
        "post_id": req.post_id,
        "description": req.description,
        "timestamp": int(time.time()),
    }

    # Add block (MVP-level — one dispute per block)
    try:
        block = chain.add_block([tx])
        logger.info("Dispute created by %s for post %s", req.user_id, req.post_id)
    except Exception as e:
        logger.warning("Chain add_block failed: %s", e)
        block = {"hash": "unrecorded"}

    DISPUTES[did] = {
        "id": did,
        "user": req.user_id,
        "post_id": req.post_id,
        "description": req.description,
        "status": "open",
        "block_hash": block["hash"],
    }
    return {"ok": True, "dispute_id": did, "block": block["hash"]}


@router.get("/{dispute_id}")
def get_dispute(dispute_id: int):
    """Return details of a dispute by ID."""
    dispute = DISPUTES.get(dispute_id)
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return dispute


@router.post("/resolve")
def resolve_dispute(req: DisputeResolve):
    """
    Resolve a dispute (MVP).
    Future versions: emit on-chain DISPUTE_RESOLVE tx
    and trigger juror payout via ledger.
    """
    d = DISPUTES.get(req.dispute_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dispute not found")

    d["status"] = "resolved"
    d["decision"] = req.decision
    d["resolver"] = req.resolver_id

    # Record on-chain
    tx = {
        "type": "DISPUTE_RESOLVE",
        "dispute_id": req.dispute_id,
        "resolver": req.resolver_id,
        "decision": req.decision,
        "timestamp": int(time.time()),
    }
    try:
        block = chain.add_block([tx])
        logger.info(
            "Dispute %s resolved by %s -> %s",
            req.dispute_id,
            req.resolver_id,
            req.decision,
        )
        d["block_hash"] = block["hash"]
    except Exception as e:
        logger.warning("Failed to record DISPUTE_RESOLVE on-chain: %s", e)

    return {"ok": True, "dispute_id": req.dispute_id, "decision": req.decision}
