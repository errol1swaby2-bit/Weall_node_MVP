"""
weall_node/api/rewards.py

Automated reward distribution: each mined block selects one winner per pool
and credits them immediately (signed mutation).
"""

from __future__ import annotations

import random
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException

# Executor façade (ledger, rewards, block mining, etc.)
from ..weall_executor import executor

# Reward pools live in the runtime ledger; fall back to empty if missing.
try:
    from ..weall_runtime.ledger import REWARD_POOLS  # type: ignore
except Exception:  # pragma: no cover
    REWARD_POOLS: Dict[str, float] = {}

router = APIRouter(prefix="/rewards", tags=["rewards"])


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

@router.post("/juror_ticket/dev")
def add_juror_ticket_dev(account_id: str, weight: float = 1.0):
    """
    DEV-ONLY: Add a juror ticket to the WeCoin 'jurors' pool.

    This lets us test juror pool rewards independently of the full
    dispute resolution pipeline. Later, dispute resolution code can
    call the same logic directly instead of this dev endpoint.
    """
    try:
        core = getattr(executor, "exec", executor)
        wecoin = getattr(core, "wecoin", None)
    except Exception:
        wecoin = None

    if wecoin is None or not hasattr(wecoin, "add_ticket"):
        raise HTTPException(status_code=503, detail="WeCoin runtime not available")

    try:
        wecoin.add_ticket("jurors", account_id, weight=float(weight))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add juror ticket: {e}")

    pool_tickets = getattr(wecoin, "tickets", {}).get("jurors", {})
    return {
        "ok": True,
        "pool": "jurors",
        "account_id": account_id,
        "weight": float(weight),
        "current_tickets": pool_tickets,
    }

@router.post("/creator_ticket/dev")
def add_creator_ticket_dev(account_id: str, weight: float = 1.0):
    """
    DEV-ONLY: Add a creator ticket to the WeCoin 'creators' pool.

    Later, content creation / engagement flows can call the same logic
    directly instead of this dev endpoint.
    """
    from ..weall_executor import executor  # local import to avoid cycles

    try:
        core = getattr(executor, "exec", executor)
        wecoin = getattr(core, "wecoin", None)
    except Exception:
        wecoin = None

    if wecoin is None or not hasattr(wecoin, "add_ticket"):
        raise HTTPException(status_code=503, detail="WeCoin runtime not available")

    try:
        wecoin.add_ticket("creators", account_id, weight=float(weight))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add creator ticket: {e}")

    pool_tickets = getattr(wecoin, "tickets", {}).get("creators", {})
    return {
        "ok": True,
        "pool": "creators",
        "account_id": account_id,
        "weight": float(weight),
        "current_tickets": pool_tickets,
    }

@router.post("/operator_ticket/dev")
def add_operator_ticket_dev(account_id: str, weight: float = 1.0):
    """
    DEV-ONLY: Add an operator ticket to the WeCoin 'operators' pool.

    Later, IPFS / uptime / compute heartbeat flows can call the same
    logic directly instead of this dev endpoint.
    """
    from ..weall_executor import executor  # local import to avoid cycles

    try:
        core = getattr(executor, "exec", executor)
        wecoin = getattr(core, "wecoin", None)
    except Exception:
        wecoin = None

    if wecoin is None or not hasattr(wecoin, "add_ticket"):
        raise HTTPException(status_code=503, detail="WeCoin runtime not available")

    try:
        wecoin.add_ticket("operators", account_id, weight=float(weight))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add operator ticket: {e}")

    pool_tickets = getattr(wecoin, "tickets", {}).get("operators", {})
    return {
        "ok": True,
        "pool": "operators",
        "account_id": account_id,
        "weight": float(weight),
        "current_tickets": pool_tickets,
    }

