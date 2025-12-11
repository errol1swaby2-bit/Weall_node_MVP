"""
weall_node/api/ops_ledger.py
---------------------------------
Ops / diagnostics surface for WeCoin + ledger invariants.

This does NOT mutate anything; it only inspects configuration and
current executor.ledger state and reports whether basic invariants
appear to hold.

Routes (mounted under /ops):

- GET /ops/ledger/meta
- GET /ops/ledger/check
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..weall_executor import executor

# We keep all runtime-ledger references defensive so this module
# doesn't explode if names move around.
try:
    from ..weall_runtime import ledger as runtime_ledger  # type: ignore[import]
except Exception:  # noqa: BLE001
    runtime_ledger = None  # type: ignore[assignment]

router = APIRouter(prefix="/ops", tags=["ops-ledger"])


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


class PoolSplitStatus(BaseModel):
    ok: bool = True
    sum: float
    pools: Dict[str, float] = Field(default_factory=dict)
    error: Optional[str] = None


class SupplyStatus(BaseModel):
    ok: bool = True
    max_supply: Optional[float] = None
    total_issued: Optional[float] = None
    remaining: Optional[float] = None
    notes: Optional[str] = None


class LedgerMeta(BaseModel):
    height: int
    latest_block_id: Optional[str] = None
    total_blocks: int
    has_wecoin_runtime: bool


class LedgerCheckResponse(BaseModel):
    ok: bool = True
    pool_split: PoolSplitStatus
    supply: SupplyStatus
    notes: Optional[str] = None


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _get_wecoin() -> Optional[Any]:
    """Return the WeCoin runtime attached to the executor, if any."""
    return getattr(executor, "wecoin", None)


def _get_runtime_attr(name: str, default: Any = None) -> Any:
    """
    Safely read an attribute from the runtime ledger module.

    We use this for invariants that rely on constants like MAX_SUPPLY
    or DEFAULT_POOL_SPLIT, while staying resilient to refactors.
    """
    if runtime_ledger is None:
        return default
    return getattr(runtime_ledger, name, default)


def _pool_split_status() -> PoolSplitStatus:
    """
    Verify that the current reward pool split sums to ~1.0 and matches
    the shape of DEFAULT_POOL_SPLIT (if available).

    This is **diagnostic only** and does not change any state.
    """
    wc = _get_wecoin()
    if wc is None:
        return PoolSplitStatus(
            ok=False,
            sum=0.0,
            pools={},
            error="wecoin_runtime_unavailable",
        )

    try:
        pools = getattr(wc, "pool_split", None)
        if not isinstance(pools, dict):
            return PoolSplitStatus(
                ok=False,
                sum=0.0,
                pools={},
                error="pool_split_not_dict",
            )
    except Exception as e:  # noqa: BLE001
        return PoolSplitStatus(
            ok=False,
            sum=0.0,
            pools={},
            error=str(e),
        )

    # If we have a DEFAULT_POOL_SPLIT defined in the runtime, make sure
    # all canonical pools are present.
    try:
        raw = getattr(runtime_ledger, "DEFAULT_POOL_SPLIT", None)
        if isinstance(raw, dict):
            missing = sorted(set(raw.keys()) - set(pools.keys()))
            if missing:
                return PoolSplitStatus(
                    ok=False,
                    sum=sum(pools.values()),
                    pools={k: float(v) for k, v in pools.items()},
                    error=f"missing_pools:{','.join(missing)}",
                )
        else:
            # If DEFAULT_POOL_SPLIT is not defined, we don't treat it
            # as a hard error, but we record it.
            if raw is None:
                # No default split at all
                return PoolSplitStatus(
                    ok=False,
                    sum=sum(pools.values()),
                    pools={k: float(v) for k, v in pools.items()},
                    error="DEFAULT_POOL_SPLIT_missing",
                )
            if not isinstance(raw, dict):
                return PoolSplitStatus(
                    ok=False,
                    sum=0.0,
                    pools={},
                    error="DEFAULT_POOL_SPLIT_missing or not a dict",
                )
    except Exception as e:  # noqa: BLE001
        return PoolSplitStatus(
            ok=False,
            sum=0.0,
            pools={},
            error=str(e),
        )

    s = sum(pools.values())
    # We allow a tiny tolerance for floating point noise.
    ok = 0.99 <= s <= 1.01

    return PoolSplitStatus(ok=ok, sum=s, pools=pools, error=None if ok else "sum_out_of_range")


def _estimate_total_supply() -> SupplyStatus:
    """
    Try to estimate total supply from executor.ledger.

    This is intentionally conservative and will return None if it
    cannot infer the structure safely.
    """
    led = getattr(executor, "ledger", None)
    max_supply = _get_runtime_attr("MAX_SUPPLY", None)

    if led is None:
        return SupplyStatus(
            ok=False,
            max_supply=max_supply,
            total_issued=None,
            remaining=None,
            notes="executor.ledger not available",
        )

    wecoin = _get_wecoin()
    if wecoin is None:
        return SupplyStatus(
            ok=False,
            max_supply=max_supply,
            total_issued=None,
            remaining=None,
            notes="wecoin runtime not attached to executor",
        )

    # We use the runtime's own total_issued if it is available.
    total_issued = getattr(wecoin, "total_issued", None)
    if total_issued is None:
        return SupplyStatus(
            ok=False,
            max_supply=max_supply,
            total_issued=None,
            remaining=None,
            notes="wecoin.total_issued not available",
        )

    try:
        total_issued = float(total_issued)
    except Exception:  # noqa: BLE001
        return SupplyStatus(
            ok=False,
            max_supply=max_supply,
            total_issued=None,
            remaining=None,
            notes="wecoin.total_issued not a float",
        )

    remaining = None
    if max_supply is not None:
        try:
            max_supply_f = float(max_supply)
            remaining = max_supply_f - total_issued
            ok = remaining >= -1e-6  # allow tiny negative due to rounding
        except Exception:  # noqa: BLE001
            ok = False
            remaining = None
    else:
        ok = True

    return SupplyStatus(
        ok=ok,
        max_supply=max_supply,
        total_issued=total_issued,
        remaining=remaining,
        notes=None if ok else "total_issued exceeds max_supply",
    )


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@router.get("/ledger/meta", response_model=LedgerMeta)
async def ledger_meta() -> LedgerMeta:
    """
    Lightweight ops metadata about the ledger and WeCoin runtime.
    """
    chain = executor.ledger.get("chain", []) or []
    height = len(chain)
    latest = chain[-1] if chain else None
    latest_id = latest["id"] if latest else None

    wc = _get_wecoin()
    has_wecoin = wc is not None

    return LedgerMeta(
        height=height,
        latest_block_id=latest_id,
        total_blocks=height,
        has_wecoin_runtime=has_wecoin,
    )


@router.get("/ledger/check", response_model=LedgerCheckResponse)
async def ledger_check() -> LedgerCheckResponse:
    """
    Run simple invariants over the WeCoin runtime:

    - pool_split should sum to ~1.0
    - pool_split keys should match DEFAULT_POOL_SPLIT (if defined)
    - total_issued should not exceed max_supply (if defined)
    """
    pool_status = _pool_split_status()
    supply_status = _estimate_total_supply()

    ok = pool_status.ok and supply_status.ok
    notes = None
    if not ok:
        notes = "One or more invariants failed; inspect pool_split and supply sections."

    return LedgerCheckResponse(
        ok=ok,
        pool_split=pool_status,
        supply=supply_status,
        notes=notes,
    )
