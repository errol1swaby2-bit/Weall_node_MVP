"""
weall_node/api/consensus.py
--------------------------------------------------
MVP consensus metadata facade.

This module does NOT drive block production yet. It simply
exposes a stable, read-only view over the chain state so
clients can inspect height, epoch, and bootstrap flags.

API:

    GET  /consensus/meta
        -> basic consensus / chain status

    POST /consensus/step-dev
        -> no-op "step" useful for wiring tests; returns
           the same meta payload with an extra note.
"""

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/consensus", tags=["consensus"])


# ============================================================
# Helpers
# ============================================================

def _derive_chain_meta() -> Dict[str, Any]:
    """
    Safely read chain information from executor.ledger["chain"].

    We support two shapes:

    1) Legacy: a list of blocks
        executor.ledger["chain"] = [ {...block...}, ... ]

    2) Structured: a dict with optional keys:
        {
            "blocks": [...],
            "height": int,
            "epoch": int,
            "bootstrap_mode": bool,
        }
    """
    raw = executor.ledger.get("chain")

    # Case 1: chain is a plain list of blocks
    if isinstance(raw, list):
        block_count = len(raw)
        height = block_count
        epoch = 0
        bootstrap_mode = False

    # Case 2: chain is a dict with metadata
    elif isinstance(raw, dict):
        blocks = raw.get("blocks")
        if isinstance(blocks, list):
            block_count = len(blocks)
        else:
            block_count = 0

        h = raw.get("height")
        if isinstance(h, int):
            height = h
        else:
            height = block_count

        epoch = int(raw.get("epoch", 0))
        bootstrap_mode = bool(raw.get("bootstrap_mode", False))

    # Case 3: missing / unknown shape
    else:
        height = 0
        epoch = 0
        bootstrap_mode = False

    return {
        "height": int(height),
        "epoch": int(epoch),
        "bootstrap_mode": bootstrap_mode,
    }


# ============================================================
# Models
# ============================================================

class ConsensusMeta(BaseModel):
    ok: bool = True
    height: int = Field(..., description="Current chain height (blocks)")
    epoch: int = Field(..., description="Current epoch index")
    bootstrap_mode: bool = Field(
        ...,
        description="True if chain is still in bootstrap / genesis mode",
    )


# ============================================================
# Routes
# ============================================================

@router.get("/meta", response_model=ConsensusMeta)
def consensus_meta() -> Dict[str, Any]:
    """
    Read-only snapshot of consensus / chain status.
    """
    meta = _derive_chain_meta()
    return {
        "ok": True,
        **meta,
    }


@router.post("/step-dev", response_model=ConsensusMeta)
def consensus_step_dev() -> Dict[str, Any]:
    """
    Dev helper: a no-op "step" that simply returns the current
    meta snapshot.

    This is intentionally conservative: it does NOT mint blocks
    or mutate chain state. It's a safe placeholder that proves
    the consensus surface is wired correctly.
    """
    return consensus_meta()
