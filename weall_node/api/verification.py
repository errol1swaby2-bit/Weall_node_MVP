#!/usr/bin/env python3
"""
weall_node/api/verification.py
----------------------------------
Unified verification facade for PoH-aware checks.

This module is intentionally thin in the current MVP:
- exposes a health-style endpoint for clients that want a
  single URL to check PoH tier and PoH subsystem status
- provides a require_poh_level() helper other modules can
  call to enforce minimum tiers

Spec alignment
--------------
- Section 3: one human → one vote (via PoH)
- Section 4: PoH tiers as the gate to higher-impact actions
- Section 6 / 7: PoH-gated participation in consensus & governance
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.weall_runtime.poh import get_poh_record

# NOTE: we do NOT set a prefix here; weall_api mounts this router
# directly, so routes will be:
#   /verification/health
#   /verification/check
router = APIRouter(prefix="/verification",tags=["verification"])
logger = logging.getLogger("verification")


# ---------------------------------------------------------------------------
# Helpers shared by HTTP layer & other modules
# ---------------------------------------------------------------------------


def _ledger_view() -> Dict[str, Any]:
    """
    Return the executor's ledger as a dict, or {} if unavailable.

    We deliberately never raise here – verification should not be able
    to crash the node if the ledger is in a funny transient state.
    """
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
    Raise HTTP 403 if the given user is below the requested PoH level.

    Intended for use by other API modules, for example:

        from weall_node.api.verification import require_poh_level

        def create_proposal(..., user_id: str, ...):
            require_poh_level(user_id, min_level=1)
            ...

    In the MVP we only check the 'tier' integer; future versions may also
    consider 'status' and reputation stages.
    """
    if min_level <= 0:
        # Tier-0 allowed – nothing to do
        return

    tier_val = current_tier(user_id)
    if tier_val < int(min_level):
        raise HTTPException(
            status_code=403,
            detail=f"PoH Tier {min_level}+ required (current tier={tier_val})",
        )


# ---------------------------------------------------------------------------
# HTTP models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """
    Simple verification subsystem health snapshot.
    """

    ok: bool
    ledger_ready: bool
    poh_records: int


class CheckReq(BaseModel):
    user_id: str
    min_level: int = 1


class CheckResp(BaseModel):
    ok: bool
    user_id: str
    tier: int
    meets_requirement: bool


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def verification_health() -> HealthResponse:
    """
    Lightweight "is PoH verification usable?" endpoint.

    - ok: always True if this endpoint responds
    - ledger_ready: True if executor.ledger is a dict
    - poh_records: number of PoH records currently in the ledger
    """
    led = _ledger_view()
    poh_bucket = led.get("poh") or {}
    recs = poh_bucket.get("records") or {}
    if not isinstance(recs, dict):
        recs = {}

    return HealthResponse(
        ok=True,
        ledger_ready=bool(led),
        poh_records=len(recs),
    )


@router.post("/check", response_model=CheckResp)
async def verification_check(body: CheckReq) -> CheckResp:
    """
    Simple verification endpoint that answers:

        "does this user meet at least min_level?"

    Intended for frontend use when it wants to know whether to show
    certain UI (e.g. governance, node-operator pages, etc.) for a given user.
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
