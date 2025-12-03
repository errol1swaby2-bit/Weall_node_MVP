#!/usr/bin/env python3
"""
Chain API
------------------------------------
Exposes blockchain state, blocks, and tokenomics metrics.
Backed by the shared executor instance (ledger['chain'] as the source of truth).
"""

import time
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..weall_executor import executor
from weall_node.weall_runtime.ledger import INITIAL_EPOCH_REWARD, HALVING_INTERVAL

router = APIRouter(prefix="/chain", tags=["chain"])
logger = logging.getLogger("chain")

if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


class BlockModel(BaseModel):
    """Public representation of a committed block."""
    height: int
    time: int
    proposer: str | None = None
    votes: list[str] = []
    prev_block_id: str | None = None
    block_id: str
    txs: list = []


def _get_core():
    """Normalize executor facade → core runtime."""
    return getattr(executor, "exec", executor)


def _get_chain_list() -> list[dict]:
    """Return the in-memory chain list from the executor ledger."""
    core = _get_core()
    ledger = getattr(core, "ledger", {}) or {}
    chain = ledger.get("chain") or []
    if not isinstance(chain, list):
        return []
    # Only keep dict-like blocks
    return [b for b in chain if isinstance(b, dict)]


@router.get("/blocks")
def get_blocks() -> list[BlockModel]:
    try:
        blocks = _get_chain_list()
        logger.info("Fetched %s blocks", len(blocks))
        out: list[BlockModel] = []
        for b in blocks:
            header = {
                "height": int(b.get("height", 0)),
                "time": int(b.get("time", b.get("ts", 0))),
                "proposer": b.get("proposer"),
                "votes": list(b.get("votes", [])),
                "prev_block_id": b.get("prev_block_id"),
                "block_id": b.get("block_id") or b.get("hash") or "",
                "txs": list(b.get("txs", [])),
            }
            out.append(BlockModel(**header))
        return out
    except Exception as e:
        logger.exception("Failed to fetch blocks: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch blocks")


@router.get("/latest")
def get_latest() -> dict:
    try:
        blocks = _get_chain_list()
        blk = blocks[-1] if blocks else None
        if not blk:
            return {}
        logger.info("Fetched latest block height=%s", blk.get("height"))
        return blk
    except Exception as e:
        logger.exception("Failed to fetch latest block: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch latest block")


@router.get("/height")
def get_chain_height() -> dict:
    try:
        height = len(_get_chain_list())
        return {"ok": True, "height": height}
    except Exception as e:
        logger.exception("Height fetch failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get chain height")


@router.get("/tokenomics")
def tokenomics_status():
    """
    Return current tokenomics state, including epoch and pool membership.
    Uses the shared executor facade from weall_executor.
    """
    try:
        core = _get_core()

        now = int(time.time())
        wecoin = getattr(core, "wecoin", None)
        if wecoin is not None:
            genesis_time = getattr(wecoin, "genesis_time", now)
            current_reward = (
                wecoin.current_epoch_reward()
                if hasattr(wecoin, "current_epoch_reward")
                else INITIAL_EPOCH_REWARD
            )
        else:
            genesis = getattr(core, "genesis", {}) or {}
            genesis_time = int(genesis.get("genesis_time") or now)
            current_reward = INITIAL_EPOCH_REWARD

        elapsed = max(0, now - genesis_time)
        halvings = elapsed // HALVING_INTERVAL
        next_halving_eta = HALVING_INTERVAL - (elapsed % HALVING_INTERVAL)

        pools: dict[str, dict[str, object]] = {}
        raw_pools = getattr(wecoin, "pools", {}) if wecoin is not None else {}
        if isinstance(raw_pools, dict):
            for name, meta in raw_pools.items():
                if isinstance(meta, dict):
                    members = list(meta.get("members", []))
                else:
                    members = list(meta or [])
                pools[name] = {"count": len(members), "members": members}

        return {
            "epoch": int(getattr(core, "current_epoch", 0)),
            "bootstrap_mode": bool(getattr(core, "bootstrap_mode", False)),
            "min_validators": int(getattr(core, "min_validators", 0)),
            "initial_epoch_reward": INITIAL_EPOCH_REWARD,
            "total_epoch_reward": current_reward,
            "halvings_so_far": int(halvings),
            "next_halving_in_seconds": int(next_halving_eta),
            "pools": pools,
        }

    except Exception as e:
        logger.exception("Tokenomics query failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch tokenomics status")
