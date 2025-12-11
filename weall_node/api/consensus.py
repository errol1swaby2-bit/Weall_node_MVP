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
           the same payload as /consensus/meta

    POST /consensus/dev/mine
        -> dev helper to call executor.mine_block() for
           single-node / local testing.
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

    # Case 2: structured dict
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

    # Prefer executor-derived flags when available
    bootstrap_flag = bool(getattr(executor, "bootstrap_mode", bootstrap_mode))
    epoch_val = getattr(executor, "current_epoch", None)
    if epoch_val is None:
        epoch_val = epoch

    return {
        "height": int(height),
        "epoch": int(epoch_val),
        "bootstrap_mode": bootstrap_flag,
    }


# ============================================================
# Models
# ============================================================


class ConsensusMeta(BaseModel):
    ok: bool = True
    height: int = Field(..., description="Current chain height (blocks)")
    epoch: int = Field(..., description="Epoch / era counter (if used)")
    bootstrap_mode: bool = Field(
        ...,
        description="True if network is still in bootstrap / genesis mode",
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


@router.post("/dev/mine")
def consensus_dev_mine() -> Dict[str, Any]:
    """
    Dev helper: mine a single block in this node's local executor.

    This is intended for single-node / Termux testing only.
    It simply delegates to `executor.mine_block()` and returns
    whatever that call returns. In particular:

    - If this node is configured as a validator and consensus is
      available, you'll get `{ "ok": true, "block": {...}, ... }`.
    - If this node is *not* allowed to participate in consensus,
      you'll typically get `{ "ok": false, "error": "node_not_validator", ... }`.

    In either case, the response is a plain dict; there is no
    additional validation layer on top.
    """
    return executor.mine_block()
