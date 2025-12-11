#!/usr/bin/env python3
"""
Operators API
---------------------------------------------------------
Handles operator registration, opt-in/out, and health status.

- Opt-in requires:
    - X-WeAll-User header
    - PoH Tier-3 (via PoH NFT check)

- Listing and health reporting remain public/read-only to
  support transparency of operator pool behaviour.
"""

from fastapi import APIRouter, HTTPException, Header, Depends, status

from weall_node.weall_runtime.wallet import has_nft
from weall_node.weall_executor import executor as executor_instance

router = APIRouter(prefix="/operators", tags=["operators"])


# ---------------------------------------------------------------
# Helper: executor access
# ---------------------------------------------------------------

def _get_executor():
    """
    Simple accessor for the global executor instance.

    Kept as a function to mirror previous lazy-loading pattern
    and for symmetry with other modules.
    """
    try:
        return executor_instance
    except Exception as e:
        raise RuntimeError(f"Executor not available: {e}")


# ---------------------------------------------------------------
# Role / tier gating helpers
# ---------------------------------------------------------------

def _require_tier3_operator(
    x_weall_user: str = Header(
        ...,
        alias="X-WeAll-User",
        description="WeAll user identifier (e.g. '@handle' or wallet id).",
    )
) -> str:
    """
    Dependency: ensure caller is PoH Tier-3 for operator actions.

    Uses PoH NFT helper:

        has_nft(user_id, "PoH", min_level=3)

    Returns the user_id (PoH id) to be used by the handler.
    """
    user_id = x_weall_user
    if not has_nft(user_id, "PoH", min_level=3):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PoH Tier-3 required to become operator",
        )
    return user_id


# ---------------------------------------------------------------
# Routes
# ---------------------------------------------------------------

@router.post("/opt-in")
def opt_in_operator(user_id: str = Depends(_require_tier3_operator)):
    """
    Opt the *current* user into the operator pool (requires PoH Tier-3).

    - Caller identity is taken from X-WeAll-User, not from a query param.
    - Prevents spoofing (you cannot opt-in someone else).
    """
    executor = _get_executor()
    try:
        result = executor.opt_in_operator(user_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Operator opt-in failed: {e}",
        )

    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Opt-in failed"),
        )

    return {"ok": True, "message": "User added to operator pool"}


@router.get("/list")
def list_operators():
    """
    List all active operators in the ledger pool.

    This endpoint is public / read-only for network transparency.
    """
    executor = _get_executor()
    try:
        pool = executor._current_operators()
        return {"ok": True, "operators": pool, "count": len(pool)}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list operators: {e}",
        )


@router.get("/health")
def operators_health():
    """
    Return basic health stats for known operators.

    The executor is expected to maintain a simple uptime/health map:

        executor.state["operator_uptime"] = {
            "<user_id>": {
                "ok": int,
                "fail": int,
                "last": float,  # last-seen timestamp
            },
            ...
        }
    """
    executor = _get_executor()
    try:
        uptime = executor.state.get("operator_uptime", {})
        report = {
            uid: {
                "ok": stats.get("ok", 0),
                "fail": stats.get("fail", 0),
                "last_seen": stats.get("last", 0),
            }
            for uid, stats in uptime.items()
        }
        return {"ok": True, "operators": report, "count": len(report)}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get operator health: {e}",
        )
