"""
weall_node/api/rewards.py

Automated reward distribution: each mined block selects one winner per pool
and credits them immediately (signed mutation).
"""

from __future__ import annotations

import random
from typing import Dict, Any, List

from fastapi import APIRouter

# Executor façade (ledger, rewards, block mining, etc.)
from ..weall_executor import executor

# Reward pools live in the runtime ledger; fall back to empty if missing.
try:
    from ..weall_runtime.ledger import REWARD_POOLS  # type: ignore
except Exception:  # pragma: no cover
    REWARD_POOLS: Dict[str, float] = {}

router = APIRouter()


def _qualified_users(pool: str) -> List[str]:
    """Users eligible to win rewards for the given pool."""
    system_keys = {"treasury_balance", "nfts", "peers"}
    return [
        uid
        for uid, val in executor.ledger.items()
        if uid not in system_keys and isinstance(val, (int, float))
    ]


def _choose_winner(pool: str) -> str:
    users = _qualified_users(pool)
    if not users:
        # Seed a dummy balance so distribution always proceeds
        dummy = f"auto_user_{pool}"
        executor.ledger.setdefault(dummy, 0.0)
        users = [dummy]
    return random.choice(users)


def _distribute_block_rewards() -> List[Dict[str, Any]]:
    """Split the per-block reward equally across pools and credit winners."""
    reward_each = executor.get_health()["reward_per_block"] / max(
        len(REWARD_POOLS) or 1, 1
    )
    payouts: List[Dict[str, Any]] = []
    for pool in REWARD_POOLS:
        winner = _choose_winner(pool)
        # Signed mutation into ledger/rewards
        executor.credit_reward(winner, pool, reward_each)
        entry = {
            "pool": pool,
            "winner": winner,
            "amount": reward_each,
            "block": executor.block_height,
        }
        executor.rewards.setdefault(pool, []).append(entry)
        payouts.append(entry)
    executor.save_state()
    return payouts


@router.get("/")
def summary() -> Dict[str, Any]:
    return {
        "ok": True,
        "block_height": executor.block_height,
        "epoch": executor.epoch,
        "reward_per_block": executor.get_health()["reward_per_block"],
        "recent_payouts": {
            p: (executor.rewards[p][-5:] if executor.rewards.get(p) else [])
            for p in REWARD_POOLS
        },
    }


@router.post("/mine")
def mine_and_distribute():
    block = executor.mine_block()
    payouts = _distribute_block_rewards()
    return {"ok": True, "block": block, "payouts": payouts}


@router.get("/winners")
def winners():
    return {
        "ok": True,
        "winners": {
            p: (executor.rewards[p][-1]["winner"] if executor.rewards.get(p) else None)
            for p in REWARD_POOLS
        },
    }


@router.get("/ledger")
def ledger_snapshot():
    return {"ok": True, "ledger": executor.ledger}


@router.post("/reset")
def reset():
    executor.reset_state()
    return {"ok": True}
