"""
weall_node/api/rewards.py
---------------------------------
MVP rewards endpoints for WeAll Node.

- /rewards/meta              -> high-level rewards config
- /rewards/pending/{user_id} -> pending rewards for a given user

This is intentionally minimal: it gives you stable JSON shapes
for the frontend & curl tests, while the actual reward accrual
logic can be wired in later via the chain module.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/rewards", tags=["rewards"])

# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------


def _init_rewards_state() -> Dict:
    """
    Ensure executor.ledger has a well-formed rewards section.
    """
    state = executor.ledger.setdefault("rewards", {})

    # Global config
    state.setdefault(
        "meta",
        {
            # chain target is 600s per block
            "epoch_length_seconds": 600,
            "pools": [
                "validators",
                "jurors",
                "creators",
                "operators",
                "treasury",
            ],
            "notes": "MVP stub – amounts are not yet wired to chain rewards.",
        },
    )

    # Per-user pending rewards: { user_id -> [RewardRecord dicts] }
    state.setdefault("pending", {})

    state.setdefault("last_update", None)

    return state


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------


class RewardRecord(BaseModel):
    """
    A single reward entry accruing to a user.

    For now only 'pool', 'amount' and 'source' really matter.
    """

    id: str = Field(..., description="Local identifier for this reward entry.")
    pool: str = Field(..., description="Which reward pool this came from.")
    amount: float = Field(..., description="Amount in WeCoin.")
    source: str = Field(
        ..., description="Human-readable source, e.g. 'block:19' or 'case:abc123'."
    )
    created_at: int = Field(..., description="Unix timestamp created.")
    mature_at: Optional[int] = Field(
        None, description="When this becomes spendable, if relevant."
    )
    paid: bool = Field(
        False, description="Whether this reward has already been paid out."
    )


class RewardsMetaResponse(BaseModel):
    ok: bool = True
    epoch_length_seconds: int
    pools: List[str]
    notes: Optional[str] = None


class PendingRewardsResponse(BaseModel):
    ok: bool = True
    user: str
    pending: List[RewardRecord]
    total_pending: float
    last_update: Optional[int] = None


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@router.get("/meta", response_model=RewardsMetaResponse)
def get_rewards_meta() -> RewardsMetaResponse:
    state = _init_rewards_state()
    meta = state["meta"]
    return RewardsMetaResponse(
        epoch_length_seconds=meta["epoch_length_seconds"],
        pools=list(meta["pools"]),
        notes=meta.get("notes"),
    )


@router.get("/pending/{user_id}", response_model=PendingRewardsResponse)
def get_pending_rewards(user_id: str) -> PendingRewardsResponse:
    """
    Return any pending rewards for a given user handle.

    For now this will usually be an empty list unless something
    manually populates executor.ledger["rewards"]["pending"].
    """
    state = _init_rewards_state()
    pending_by_user: Dict[str, List[Dict]] = state["pending"]
    last_update = state.get("last_update")

    raw_list: List[Dict] = pending_by_user.get(user_id, [])
    records = [RewardRecord(**item) for item in raw_list]
    total = float(sum(r.amount for r in records))

    return PendingRewardsResponse(
        user=user_id,
        pending=records,
        total_pending=total,
        last_update=last_update,
    )
