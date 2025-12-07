"""
weall_node/api/treasury.py
---------------------------------
MVP treasury endpoints for WeAll Node.

- /treasury/meta  -> monetary policy & pool splits
- /treasury/pools -> current pool balances (stubbed for now)

Data is stored in executor.ledger["treasury"].
"""

from typing import Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/treasury", tags=["treasury"])

# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------


def _init_treasury_state() -> Dict:
    """
    Ensure executor.ledger has a well-formed treasury section.
    Returns the mutable state dict.
    """
    state = executor.ledger.setdefault("treasury", {})

    # Monetary policy – aligned with Full Scope spec
    state.setdefault(
        "meta",
        {
            "initial_block_reward": 100.0,
            # 2 years in seconds
            "halving_interval_seconds": 2 * 365 * 24 * 3600,
            # 5×20% split, expressed in basis points (10000 = 100%)
            "pool_splits_bps": {
                "validators": 2000,
                "jurors": 2000,
                "creators": 2000,
                "operators": 2000,
                "treasury": 2000,
            },
        },
    )

    # Pool balances – all zero for the local single-node dev chain
    state.setdefault(
        "pools",
        {
            "validators": 0.0,
            "jurors": 0.0,
            "creators": 0.0,
            "operators": 0.0,
            "treasury": 0.0,
        },
    )

    state.setdefault("last_update", None)

    return state


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------


class TreasuryMetaResponse(BaseModel):
    ok: bool = True
    initial_block_reward: float = Field(
        ..., description="Initial block reward in WeCoin."
    )
    halving_interval_seconds: int = Field(
        ..., description="Seconds between reward halvings."
    )
    pool_splits_bps: Dict[str, int] = Field(
        ..., description="Split of block reward per pool, in basis points."
    )


class TreasuryPoolsResponse(BaseModel):
    ok: bool = True
    pools: Dict[str, float] = Field(
        ..., description="Current balances per pool (WeCoin)."
    )
    last_update: Optional[int] = Field(
        None,
        description="Unix timestamp of last treasury update, or null if never.",
    )


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@router.get("/meta", response_model=TreasuryMetaResponse)
def get_treasury_meta() -> TreasuryMetaResponse:
    """
    Return static monetary policy + pool split config.
    """
    state = _init_treasury_state()
    meta = state["meta"]
    return TreasuryMetaResponse(**meta)


@router.get("/pools", response_model=TreasuryPoolsResponse)
def get_treasury_pools() -> TreasuryPoolsResponse:
    """
    Return current per-pool balances.

    In the current MVP these are stubbed to zeros and will later
    be updated by the block-production / rewards pipeline.
    """
    state = _init_treasury_state()
    pools = state["pools"]
    last_update = state.get("last_update")
    return TreasuryPoolsResponse(pools=pools, last_update=last_update)
