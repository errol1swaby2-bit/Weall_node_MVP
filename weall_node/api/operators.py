#!/usr/bin/env python3
"""
Operators API
---------------------------------------------------------
Handles operator registration, opt-in/out, and health status.
Uses lazy import of executor_instance to avoid circular import.
"""

from fastapi import APIRouter, HTTPException, Query
from weall_node.weall_runtime.wallet import has_nft

router = APIRouter(prefix="/operators", tags=["operators"])


# ---------------------------------------------------------------
# Helper: lazy-load executor_instance
# ---------------------------------------------------------------
def _get_executor():
    try:
        from weall_node.weall_api import executor_instance

        return executor_instance
    except Exception as e:
        raise RuntimeError(f"Executor not available: {e}")


# ---------------------------------------------------------------
# Routes
# ---------------------------------------------------------------
@router.post("/opt-in")
def opt_in_operator(user_id: str = Query(...)):
    """
    Opt a user into the operator pool (requires PoH Tier-3).
    """
    if not has_nft(user_id, "PoH", min_level=3):
        raise HTTPException(
            status_code=401, detail="PoH Tier-3 required to become operator"
        )

    executor = _get_executor()
    result = executor.opt_in_operator(user_id)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Opt-in failed")
        )
    return {"ok": True, "message": "User added to operator pool"}


@router.post("/opt-out")
def opt_out_operator(user_id: str = Query(...)):
    """
    Opt a user out of the operator pool.
    """
    executor = _get_executor()
    result = executor.opt_out_operator(user_id)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400, detail=result.get("error", "Opt-out failed")
        )
    return {"ok": True, "message": "User removed from operator pool"}


@router.get("/list")
def list_operators():
    """
    List all active operators in the ledger pool.
    """
    executor = _get_executor()
    try:
        pool = executor._current_operators()
        return {"ok": True, "operators": pool, "count": len(pool)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list operators: {e}")


@router.get("/health")
def operator_health():
    """
    Return uptime and participation stats for all operators.
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
            status_code=500, detail=f"Failed to get operator health: {e}"
        )
