#!/usr/bin/env python3
"""
Validators API
---------------------------------------------------------
Handles validator registration, opt-in/out, and status checks.
Uses lazy import of executor_instance to avoid circular import.
"""

from fastapi import APIRouter, HTTPException, Query
from weall_node.weall_runtime.wallet import has_nft

router = APIRouter(prefix="/validators", tags=["validators"])

# ---------------------------------------------------------------
# Helper: lazy-load executor_instance to break circular import
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
def opt_in_validator(user_id: str = Query(...)):
    """
    Opt a user into the validator pool (requires PoH Tier-3).
    """
    if not has_nft(user_id, "PoH", min_level=3):
        raise HTTPException(status_code=401, detail="PoH Tier-3 required to become validator")

    executor = _get_executor()
    result = executor.opt_in_validator(user_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Opt-in failed"))
    return {"ok": True, "message": "User added to validator pool"}


@router.post("/opt-out")
def opt_out_validator(user_id: str = Query(...)):
    """
    Opt a user out of the validator pool.
    """
    executor = _get_executor()
    result = executor.opt_out_validator(user_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Opt-out failed"))
    return {"ok": True, "message": "User removed from validator pool"}


@router.get("/list")
def list_validators():
    """
    Return the current list of validators.
    """
    executor = _get_executor()
    try:
        vals = executor.get_validators()
        return {"ok": True, "validators": vals, "count": len(vals)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list validators: {e}")


@router.get("/status/{user_id}")
def validator_status(user_id: str):
    """
    Check if a user is currently an active validator.
    """
    executor = _get_executor()
    try:
        is_val = executor.is_validator(user_id)
        return {"ok": True, "user_id": user_id, "is_validator": bool(is_val)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {e}")


@router.post("/run")
def run_validator_epoch(user_id: str = Query(...)):
    """
    Execute validator role for the current epoch (if elected).
    """
    if not has_nft(user_id, "PoH", min_level=3):
        raise HTTPException(status_code=401, detail="PoH Tier-3 required to run validator")

    executor = _get_executor()
    try:
        result = executor.run_validator(user_id)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validator execution failed: {e}")
