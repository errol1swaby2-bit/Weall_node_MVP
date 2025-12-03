#!/usr/bin/env python3
"""
weall_node/api/verification.py
----------------------------------
Unified verification facade for PoH-aware checks.

This module is intentionally thin in the current MVP:
- exposes a health-style endpoint for clients that want a
  single URL to check PoH tier
- provides a require_poh_level() helper other modules can
  call to enforce minimum tiers

Spec alignment
--------------
- Section 3: one human → one vote (via PoH)
- Section 6 / 7: PoH-gated participation in consensus & governance
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.weall_runtime.poh import get_poh_record

router = APIRouter(prefix="/verification", tags=["verification"])
logger = logging.getLogger("verification")


# ---------------------------------------------------------------------------
# Helpers shared by HTTP layer & other modules
# ---------------------------------------------------------------------------

def _ledger() -> Dict[str, Any]:
    led = getattr(executor, "ledger", None)
    if not isinstance(led, dict):
        return {}
    return led  # type: ignore[return-value]


def current_tier(user_id: str) -> int:
    """
    Read the current PoH tier for a user from the ledger.
    Falls back to 0 if no record is present.
    """
    rec = get_poh_record(user_id)
    if not rec:
        return 0
    try:
        return int(rec.get("tier", 0))
    except Exception:
        return 0


def require_poh_level(user_id: str, min_level: int) -> None:
    """
    Raise HTTP 403 if the user does not meet the required PoH level.

    This is a convenience wrapper for enforceable API routes, separate
    from the more generic security.permissions module which operates
    at a slightly lower level.
    """
    if min_level <= 0:
        return

    tier_val = current_tier(user_id)
    if tier_val < int(min_level):
        raise HTTPException(status_code=403, detail=f"PoH Tier {min_level}+ required")


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

class CheckReq(BaseModel):
    user_id: str
    min_level: int = 1


class CheckResp(BaseModel):
    ok: bool
    user_id: str
    tier: int
    meets_requirement: bool


@router.post("/check", response_model=CheckResp)
async def verification_check(body: CheckReq) -> CheckResp:
    """
    Simple verification endpoint that answers:
        "does this user meet at least min_level?"
    """
    uid = (body.user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id required")

    tier_val = current_tier(uid)
    meets = tier_val >= int(body.min_level)

    return CheckResp(
        ok=True,
        user_id=uid,
        tier=tier_val,
        meets_requirement=meets,
    )
