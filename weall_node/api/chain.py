#!/usr/bin/env python3
"""
Chain API
------------------------------------
Exposes blockchain state, blocks, and tokenomics metrics.
Integrates with the shared executor_instance (lazy import to avoid circulars).
"""

import time, logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from weall_node.app_state import chain
from weall_node.weall_runtime.ledger import INITIAL_EPOCH_REWARD, HALVING_INTERVAL

router = APIRouter(prefix="/chain", tags=["chain"])
logger = logging.getLogger("chain")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class BlockModel(BaseModel):
    ts: int
    txs: list
    prev: str | None = None
    hash: str


# -------------------------------
# Routes
# -------------------------------
@router.get("/blocks")
def get_blocks() -> list[BlockModel]:
    try:
        blocks = chain.all_blocks()
        logger.info("Fetched %s blocks", len(blocks))
        return blocks
    except Exception as e:
        logger.exception("Failed to fetch blocks: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch blocks")


@router.get("/latest")
def get_latest() -> dict:
    try:
        blk = chain.latest()
        if not blk:
            raise HTTPException(status_code=404, detail="No blocks found")
        return blk
    except Exception as e:
        logger.exception("Failed to fetch latest block: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch latest block")


@router.get("/height")
def get_chain_height() -> dict:
    try:
        height = len(chain.all_blocks())
        return {"ok": True, "height": height}
    except Exception as e:
        logger.exception("Height fetch failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get chain height")


@router.get("/tokenomics")
def tokenomics_status():
    """
    Return current tokenomics state.
    (Lazy-imports weall_api.executor_instance to avoid circular dependency.)
    """
    try:
        from weall_node.weall_api import executor_instance  # lazy import here

        now = int(time.time())
        wecoin = getattr(executor_instance.ledger, "wecoin", None)
        genesis_time = getattr(wecoin, "genesis_time", now)
        current_reward = wecoin.current_epoch_reward() if hasattr(wecoin, "current_epoch_reward") else INITIAL_EPOCH_REWARD
        elapsed = now - genesis_time
        halvings = elapsed // HALVING_INTERVAL
        next_halving_eta = HALVING_INTERVAL - (elapsed % HALVING_INTERVAL)

        pools = {}
        raw_pools = getattr(wecoin, "pools", {})
        for name, meta in raw_pools.items():
            members = list(meta.get("members", [])) if isinstance(meta, dict) else list(meta)
            pools[name] = {"count": len(members), "members": members}

        return {
            "epoch": getattr(executor_instance, "current_epoch", 0),
            "bootstrap_mode": getattr(executor_instance, "bootstrap_mode", False),
            "min_validators": getattr(executor_instance, "min_validators", 0),
            "initial_epoch_reward": INITIAL_EPOCH_REWARD,
            "total_epoch_reward": current_reward,
            "halvings_so_far": int(halvings),
            "next_halving_in_seconds": int(next_halving_eta),
            "pools": pools,
        }

    except Exception as e:
        logger.exception("Tokenomics query failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch tokenomics status")

