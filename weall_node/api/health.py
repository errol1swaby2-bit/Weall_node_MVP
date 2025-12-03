"""
weall_node/api/health.py
--------------------------------------------------
Unified health + readiness endpoint for WeAll Node.
Reports validator progress, operator (IPFS) status, uptime, and block metrics.
"""

from fastapi import APIRouter
from ..weall_executor import executor

router = APIRouter()


@router.get("/")
def get_health():
    """Return composite node health summary."""
    return executor.get_health()


@router.get("/readyz")
def get_ready_state():
    """
    Lightweight readiness probe.
    OK if node has mined at least one block and IPFS layer is reachable.
    """
    h = executor.get_health()
    ready = h["block_height"] > 0 and h["ipfs"].get("ok")
    return {"ready": ready, "details": h}


@router.get("/metrics")
def get_metrics():
    """
    Returns high-level node metrics useful for monitoring.
    """
    h = executor.get_health()
    totals = {p: len(v) for p, v in executor.rewards.items()}
    return {
        "block_height": h["block_height"],
        "epoch": h["epoch"],
        "reward_per_block": h["reward_per_block"],
        "reward_entries": totals,
        "uptime_sec": h["uptime_sec"],
        "ipfs_ok": h["ipfs"].get("ok", False),
    }

@router.get("/p2p")
def get_p2p():
    """
    Return basic P2P peer info for the top nav badge.
    Shape: { ok: true, peers: <int>, peer_ids: [...] }
    """
    peers = []
    try:
        peers = executor.get_peer_list()
    except Exception:
        peers = []
    return {
        "ok": True,
        "peers": len(peers),
        "peer_ids": peers,
    }

