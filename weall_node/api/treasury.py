"""
weall_node/api/treasury.py
---------------------------------
Treasury endpoints for WeAll Node.

This module exposes a read-only view of the protocol-level monetary policy
and the network treasury account, backed by the WeCoin runtime:

    - GET /treasury/meta
        → monetary policy, halving schedule, pool split

    - GET /treasury/pools
        → current treasury balance & pool split snapshot

Unlike the original MVP, this version no longer relies on stubbed balances
inside executor.ledger["treasury"]. Instead it reflects the live WeCoin
runtime (if available) and falls back to sensible defaults when it is not.

Slashing is *not* handled here; the only punitive action in WeAll is
account-level bans managed elsewhere in the protocol.
"""

from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/treasury", tags=["treasury"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wecoin():
    """
    Convenience accessor for the WeCoin runtime.

    Returns None if the runtime is not available (e.g., in certain unit tests
    or dev shells).
    """
    return getattr(executor, "wecoin", None)


def _pool_split_bps(split: Dict[str, float]) -> Dict[str, int]:
    """
    Convert a {pool: fraction} mapping into basis-points (1/100 of a percent).

    Assumes split fractions sum to ~1.0, but we do not rely on this strictly.
    """
    out: Dict[str, int] = {}
    for name, frac in (split or {}).items():
        try:
            bps = int(round(float(frac) * 10_000))
        except Exception:
            bps = 0
        out[str(name)] = bps
    return out


def _current_block_reward(wec) -> float:
    """
    Compute the current block reward using the runtime's own monetary policy.

    If the runtime exposes a private helper, we try to call it on the latest
    height; otherwise we approximate by calling it at the current chain height.
    """
    if wec is None:
        return 0.0

    # Try to derive height from the chain
    chain = executor.ledger.get("chain") or []
    height = len(chain)
    try:
        # New WeCoinLedger exposes a _current_block_reward helper
        if hasattr(wec, "_current_block_reward"):
            return float(wec._current_block_reward(height))  # type: ignore[attr-defined]
    except Exception:
        pass

    # Fallback: if no helper is available, approximate using initial reward
    try:
        return float(getattr(wec, "initial_block_reward", 0.0))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TreasuryMetaResponse(BaseModel):
    ok: bool = True
    token_symbol: str = Field("WEC", description="Human-readable token ticker.")
    max_supply: float = Field(..., description="Maximum WEC supply (hard cap).")
    total_issued: float = Field(
        ...,
        description="Total WEC that have been minted and credited so far.",
    )
    initial_block_reward: float = Field(
        ...,
        description="Reward per block at height 0, before any halvings.",
    )
    current_block_reward: float = Field(
        ...,
        description="Estimated reward per block at the current chain height.",
    )
    block_interval_seconds: int = Field(
        ...,
        description="Target block interval in seconds (e.g., 600 = 10 minutes).",
    )
    halving_interval_seconds: int = Field(
        ...,
        description="Time between reward halvings, in seconds.",
    )
    blocks_per_epoch: int = Field(
        ...,
        description="Configured blocks-per-epoch used by the node.",
    )
    bootstrap_mode: bool = Field(
        ...,
        description="True when Genesis Safety Mode / bootstrap mode is active.",
    )
    pool_split_bps: Dict[str, int] = Field(
        ...,
        description="Per-pool share of each block reward, in basis points.",
    )


class TreasuryPoolsResponse(BaseModel):
    ok: bool = True
    treasury_account: str = Field(
        "@weall_treasury",
        description="Designated treasury account id.",
    )
    treasury_balance: float = Field(
        ...,
        description="Current WEC balance of the treasury account.",
    )
    total_issued: float = Field(
        ...,
        description="Total WEC that have been minted and credited so far.",
    )
    pool_split_bps: Dict[str, int] = Field(
        ...,
        description="Per-pool share of each block reward, in basis points.",
    )
    last_update: Optional[int] = Field(
        None,
        description="Reserved for future on-ledger snapshot timestamps.",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/meta", response_model=TreasuryMetaResponse)
def get_treasury_meta() -> TreasuryMetaResponse:
    """
    Return a snapshot of the network's monetary policy and pool split.

    This data is derived from the live WeCoin runtime when possible, and
    falls back to defaults baked into the executor and runtime in dev mode.
    """
    wec = _wecoin()

    # Derive policy from runtime if available
    if wec is not None:
        max_supply = float(getattr(wec, "max_supply", 0.0))
        total_issued = float(getattr(wec, "total_issued", 0.0))
        initial_block_reward = float(getattr(wec, "initial_block_reward", 0.0))
        block_interval_seconds = int(getattr(wec, "block_interval_seconds", 600))
        halving_interval_seconds = int(getattr(wec, "halving_interval_seconds", 0))
        pool_split = getattr(wec, "pool_split", {}) or {}
    else:
        # Minimal safe defaults if runtime is missing
        max_supply = 21_000_000.0
        total_issued = 0.0
        initial_block_reward = 100.0
        block_interval_seconds = 600
        # 2-year halving, matching weall_runtime.ledger default
        halving_interval_seconds = 2 * 365 * 24 * 60 * 60
        pool_split = {
            "validators": 0.20,
            "jurors": 0.20,
            "creators": 0.20,
            "operators": 0.20,
            "treasury": 0.20,
        }

    current_block_reward = _current_block_reward(wec)

    blocks_per_epoch = int(getattr(executor, "blocks_per_epoch", 100))
    bootstrap_mode = bool(getattr(executor, "bootstrap_mode", False))
    pool_split_bps = _pool_split_bps(pool_split)

    return TreasuryMetaResponse(
        max_supply=max_supply,
        total_issued=total_issued,
        initial_block_reward=initial_block_reward,
        current_block_reward=current_block_reward,
        block_interval_seconds=block_interval_seconds,
        halving_interval_seconds=halving_interval_seconds,
        blocks_per_epoch=blocks_per_epoch,
        bootstrap_mode=bootstrap_mode,
        pool_split_bps=pool_split_bps,
    )


@router.get("/pools", response_model=TreasuryPoolsResponse)
def get_treasury_pools() -> TreasuryPoolsResponse:
    """
    Return the current treasury balance plus the pool split snapshot.

    At Genesis, only the treasury account has a dedicated on-ledger address
    (@weall_treasury). Other pools (validators, jurors, creators, operators)
    distribute rewards directly to individual account balances rather than
    accumulating into a shared pool account, so their "balances" are not
    exposed here.

    For analytics, higher-level tooling can aggregate balances by role;
    this endpoint focuses on protocol-level monetary policy plus the
    canonical commons pool balance.
    """
    wec = _wecoin()

    if wec is not None:
        treasury_balance = float(wec.get_balance("@weall_treasury"))
        total_issued = float(getattr(wec, "total_issued", 0.0))
        pool_split = getattr(wec, "pool_split", {}) or {}
    else:
        treasury_balance = 0.0
        total_issued = 0.0
        pool_split = {
            "validators": 0.20,
            "jurors": 0.20,
            "creators": 0.20,
            "operators": 0.20,
            "treasury": 0.20,
        }

    pool_split_bps = _pool_split_bps(pool_split)

    # We keep last_update reserved for future on-ledger summaries; for now, None.
    return TreasuryPoolsResponse(
        treasury_balance=treasury_balance,
        total_issued=total_issued,
        pool_split_bps=pool_split_bps,
        last_update=None,
    )
