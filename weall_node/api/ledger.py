"""
API: /ledger

Read-only endpoints exposing WeCoin monetary policy, balances, and
reward pool configuration.

This is intentionally "thin": all actual monetary logic lives in
weall_runtime.ledger.WeCoinLedger and is driven by WeAllExecutor.
"""

from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from weall_node.weall_executor import executor
from weall_node.weall_runtime.ledger import (
    MAX_SUPPLY,
    INITIAL_BLOCK_REWARD,
    BLOCK_INTERVAL_SECONDS,
    HALVING_INTERVAL_SECONDS,
    BLOCKS_PER_HALVING,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _wecoin() -> Any:
    """
    Return the WeCoin runtime attached to the executor, or raise 503
    if the runtime is not available.

    This uses the global executor facade defined in weall_executor.py,
    which exposes .wecoin as an attribute.
    """
    wc = getattr(executor, "wecoin", None)
    if wc is None:
        raise HTTPException(
            status_code=503, detail="wecoin_runtime_unavailable"
        )
    return wc


def _chain() -> list:
    return executor.ledger.get("chain", []) or []


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------


@router.get("/health")
async def ledger_health() -> Dict[str, Any]:
    """
    Lightweight health check for the ledger / WeCoin runtime.
    """
    chain = _chain()
    height = len(chain)
    latest = chain[-1] if chain else None

    wc = getattr(executor, "wecoin", None)
    wecoin_ok = wc is not None

    return {
        "ok": True,
        "has_chain": bool(chain),
        "height": height,
        "latest_block_id": latest["id"] if latest else None,
        "wecoin_attached": wecoin_ok,
    }


@router.get("/params")
async def ledger_params() -> Dict[str, Any]:
    """
    Return the global monetary policy parameters.

    These reflect the Full Scope v2 spec (21M cap, 100 WCN initial
    block reward, 10-minute blocks, ~2-year halving).
    """
    wc = _wecoin()

    # Allow runtime to override the global constants; fall back to
    # module-level defaults if attributes are missing.
    max_supply = getattr(wc, "max_supply", MAX_SUPPLY)
    initial_reward = getattr(wc, "initial_block_reward", INITIAL_BLOCK_REWARD)
    block_interval = getattr(wc, "block_interval_seconds", BLOCK_INTERVAL_SECONDS)
    halving_secs = getattr(wc, "halving_interval_seconds", HALVING_INTERVAL_SECONDS)

    return {
        "ok": True,
        "max_supply": float(max_supply),
        "initial_block_reward": float(initial_reward),
        "block_interval_seconds": int(block_interval),
        "halving_interval_seconds": int(halving_secs),
        "blocks_per_halving": int(BLOCKS_PER_HALVING),
    }


@router.get("/supply")
async def supply_meta() -> Dict[str, Any]:
    """
    Return supply information: total issued so far and headroom
    to the max supply.
    """
    wc = _wecoin()

    max_supply = float(getattr(wc, "max_supply", MAX_SUPPLY))
    total_issued = float(getattr(wc, "total_issued", 0.0))
    remaining = max(0.0, max_supply - total_issued)

    return {
        "ok": True,
        "max_supply": max_supply,
        "total_issued": total_issued,
        "remaining": remaining,
    }


@router.get("/balance/{account_id}")
async def get_balance(account_id: str) -> Dict[str, Any]:
    """
    Return the balance of a single account in WCN.
    """
    wc = _wecoin()
    try:
        balance = float(wc.get_balance(account_id))
    except Exception:
        balance = 0.0

    return {
        "ok": True,
        "account_id": account_id,
        "balance": balance,
    }


@router.get("/pools")
async def pools_meta() -> Dict[str, Any]:
    """
    Return the current reward pool split and, if available, each
    pool's tickets snapshot and membership.

    This exposes the five canonical pools:

        validators, jurors, creators, operators, treasury
    """
    wc = _wecoin()

    pool_split = getattr(wc, "pool_split", {}) or {}
    pools = getattr(wc, "pools", {}) or {}
    tickets = getattr(wc, "tickets", {}) or {}

    formatted: Dict[str, Any] = {}
    for pool_name, fraction in pool_split.items():
        members = []
        try:
            members = sorted(list(pools.get(pool_name, {}).get("members", [])))
        except Exception:
            members = []

        pool_tickets = tickets.get(pool_name, {}) or {}
        # Only return non-zero tickets for readability
        nonzero_tickets = {
            aid: float(w)
            for aid, w in pool_tickets.items()
            if float(w or 0.0) > 0.0
        }

        formatted[pool_name] = {
            "fraction": float(fraction),
            "members": members,
            "tickets": nonzero_tickets,
        }

    return {
        "ok": True,
        "pools": formatted,
    }


@router.get("/chain")
async def chain_meta() -> Dict[str, Any]:
    """
    Return high-level chain metadata useful for UIs:

    - height
    - latest block header
    - simple halving schedule hints
    """
    chain = _chain()
    height = len(chain)
    latest = chain[-1] if chain else None

    wc = getattr(executor, "wecoin", None)
    max_supply = float(getattr(wc, "max_supply", MAX_SUPPLY)) if wc else MAX_SUPPLY
    total_issued = float(getattr(wc, "total_issued", 0.0)) if wc else 0.0

    return {
        "ok": True,
        "height": height,
        "latest_block": latest,
        "max_supply": max_supply,
        "total_issued": total_issued,
    }
