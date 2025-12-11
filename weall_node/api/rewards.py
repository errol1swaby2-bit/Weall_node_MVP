"""
weall_node/api/rewards.py
---------------------------------
Rewards metadata + pending-rewards view for WeAll Node.

Endpoints:

    GET  /rewards/meta
        → high-level rewards + epoch config, derived from the WeCoin runtime

    GET  /rewards/pending/{user_id}
        → MVP view of locally-tracked pending rewards records for a user

This module does NOT perform any minting, staking, or slashing. All actual
WeCoin issuance is handled by the WeCoinLedger in weall_runtime/ledger.py.
The "pending" view here is purely a UX/analytics convenience that higher-
level systems may populate from events or off-chain accounting.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/rewards", tags=["rewards"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wecoin():
    """Convenience accessor for the WeCoin runtime (may be None)."""
    return getattr(executor, "wecoin", None)


def _pool_split_bps(split: Dict[str, float]) -> Dict[str, int]:
    """
    Convert a {pool: fraction} mapping into basis-points (1/100 of a percent).
    """
    out: Dict[str, int] = {}
    for name, frac in (split or {}).items():
        try:
            out[str(name)] = int(round(float(frac) * 10_000))
        except Exception:
            out[str(name)] = 0
    return out


def _default_pools() -> List[str]:
    """
    Canonical list of reward pools as per Full Scope v2.
    """
    return [
        "validators",
        "jurors",
        "creators",
        "operators",
        "treasury",
    ]


def _init_rewards_state() -> Dict:
    """
    Ensure executor.ledger has a well-formed rewards section and
    hydrate its meta from the WeCoin ledger runtime when available.

    Layout:

        executor.ledger["rewards"] = {
            "pending": {
                "<user_id>": [
                    {
                        "pool": "validators" | "jurors" | ...,
                        "amount": float,
                        "source": str,
                        "created_at": int,
                    },
                    ...
                ],
            },
            "last_update": int | None,
        }
    """
    state = executor.ledger.setdefault("rewards", {})
    state.setdefault("pending", {})
    state.setdefault("last_update", None)
    return state


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RewardsMetaResponse(BaseModel):
    ok: bool = True
    token_symbol: str = Field("WEC", description="Human-readable token ticker.")
    pools: List[str] = Field(
        ...,
        description="Logical reward pools used by the protocol.",
    )
    pool_split_bps: Dict[str, int] = Field(
        ...,
        description="Per-pool share of each block reward, in basis points.",
    )
    block_interval_seconds: int = Field(
        ...,
        description="Target block interval in seconds.",
    )
    blocks_per_epoch: int = Field(
        ...,
        description="Configured blocks-per-epoch used for epoch accounting.",
    )
    epoch_length_seconds: int = Field(
        ...,
        description="Derived epoch duration in seconds.",
    )
    bootstrap_mode: bool = Field(
        ...,
        description="True when Genesis Safety Mode / bootstrap mode is active.",
    )
    notes: str = Field(
        "",
        description="Human-readable notes about reward configuration.",
    )


class RewardRecord(BaseModel):
    """
    Lightweight record describing a single pending reward entry.

    This is intentionally generic so it can represent different sources
    (e.g., "block", "dispute_case", "content_engagement", etc.).
    """
    pool: str = Field(
        ...,
        description="Reward pool this entry belongs to (validators/jurors/creators/operators/treasury).",
    )
    amount: float = Field(
        ...,
        description="Nominal WEC amount represented by this entry.",
    )
    source: str = Field(
        ...,
        description="Free-form source identifier (e.g., 'block:123', 'dispute:xyz').",
    )
    created_at: int = Field(
        ...,
        description="Unix timestamp when this record was created.",
    )


class PendingRewardsResponse(BaseModel):
    ok: bool = True
    user: str
    pending: List[RewardRecord]
    total_pending: float
    last_update: Optional[int]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/meta", response_model=RewardsMetaResponse)
def rewards_meta() -> RewardsMetaResponse:
    """
    High-level rewards configuration derived from WeCoin + executor.

    This gives the frontend enough information to:

      - Display epoch length (seconds, blocks)
      - Show the pool split in basis-points
      - Indicate whether GSM / bootstrap_mode is active
    """
    wec = _wecoin()

    if wec is not None:
        block_interval_seconds = int(getattr(wec, "block_interval_seconds", 600))
        pool_split = getattr(wec, "pool_split", {}) or {}
        token_symbol = "WEC"
    else:
        block_interval_seconds = 600
        token_symbol = "WEC"
        pool_split = {
            "validators": 0.20,
            "jurors": 0.20,
            "creators": 0.20,
            "operators": 0.20,
            "treasury": 0.20,
        }

    blocks_per_epoch = int(getattr(executor, "blocks_per_epoch", 100))
    epoch_length_seconds = blocks_per_epoch * block_interval_seconds
    bootstrap_mode = bool(getattr(executor, "bootstrap_mode", False))
    pools = sorted(pool_split.keys()) or _default_pools()
    pool_split_bps = _pool_split_bps(pool_split)

    return RewardsMetaResponse(
        token_symbol=token_symbol,
        pools=pools,
        pool_split_bps=pool_split_bps,
        block_interval_seconds=block_interval_seconds,
        blocks_per_epoch=blocks_per_epoch,
        epoch_length_seconds=epoch_length_seconds,
        bootstrap_mode=bootstrap_mode,
        notes="Pool split and epoch timing derived from WeCoin runtime and node genesis params.",
    )


@router.get("/pending/{user_id}", response_model=PendingRewardsResponse)
def pending_rewards(user_id: str) -> PendingRewardsResponse:
    """
    MVP view of pending rewards entries for a user.

    This does NOT attempt to compute protocol-accurate per-user accrual based
    on full WeCoin history; instead it surfaces any entries that have been
    recorded into executor.ledger['rewards']['pending'][user_id] by higher-
    level modules or background jobs.

    For production protocols, a dedicated accounting / indexing layer would
    usually compute these values from on-chain events and store them here.
    """
    if not user_id:
        return PendingRewardsResponse(
            ok=True,
            user="",
            pending=[],
            total_pending=0.0,
            last_update=None,
        )

    state = _init_rewards_state()
    pending_by_user: Dict[str, List[Dict]] = state["pending"]
    last_update = state.get("last_update")

    raw_list: List[Dict] = pending_by_user.get(user_id, [])
    records = [RewardRecord(**item) for item in raw_list]
    total = float(sum(r.amount for r in records))

    return PendingRewardsResponse(
        ok=True,
        user=user_id,
        pending=records,
        total_pending=total,
        last_update=last_update,
    )
