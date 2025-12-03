"""
weall_node/api/poh.py
----------------------------------
FastAPI router for Proof-of-Humanity operations.

Goals for this version:
- Persist all PoH state in executor.ledger["poh"] (no in-memory STATE dicts)
- Provide Tier-2 async verification endpoints used by the web SDK
- Expose a simple /poh/status endpoint for frontends & auth gates

Spec alignment
--------------
- Section 3.2 / 3.3 / 3.4: Tier flows
- Section 3.5: Revocation & recovery (via ledger-backed records)
- Section 8.3: Juror votes on Tier-2 applications
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor
from weall_node.weall_runtime.poh import (
    poh_runtime,
    get_poh_record,
    set_poh_tier,
    get_t2_config,
    update_t2_config,
    get_t2_queue,
    upsert_t2_application,
    register_t2_vote,
)
from weall_node.weall_runtime.wallet import ensure_poh_badge  # type: ignore


logger = logging.getLogger("poh")
router = APIRouter(prefix="/poh", tags=["poh"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class StatusReq(BaseModel):
    account_id: str = Field(..., description="Logical account/user id")


class StatusResp(BaseModel):
    ok: bool
    account_id: str
    tier: int
    revoked: bool
    source: Optional[str] = None
    updated_at: Optional[int] = None
    revocation_reason: Optional[str] = None


class T2SubmitReq(BaseModel):
    account_id: str
    videos: List[str] = Field(default_factory=list)
    title: str = ""
    desc: str = ""


class T2ListReq(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="Optional filter: pending / approved / rejected",
    )
    limit: int = 50
    offset: int = 0


class T2VoteReq(BaseModel):
    candidate_id: str
    juror_id: str
    approve: bool


class T2ItemReq(BaseModel):
    account_id: str


class T2ConfigReq(BaseModel):
    required_yes: Optional[int] = None
    max_pending: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_executor_ledger() -> Dict[str, Any]:
    led = getattr(executor, "ledger", None)
    if not isinstance(led, dict):
        raise HTTPException(status_code=500, detail="Ledger not initialised")
    return led


def _persist() -> None:
    try:
        save_state = getattr(executor, "save_state", None)
        if callable(save_state):
            save_state()
    except Exception as exc:  # pragma: no cover - logging only
        logger.warning("Failed to save state after PoH update: %r", exc)


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.post("/status", response_model=StatusResp)
async def poh_status(body: StatusReq) -> StatusResp:
    """
    Return the current PoH status for a given account.

    This is the endpoint used by:
      - websdk.js → api.pohStatus()
      - frontend/auth.js PoH gates
    """
    account_id = (body.account_id or "").strip()
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")

    _ensure_executor_ledger()

    rec = get_poh_record(account_id) or {
        "tier": 0,
        "revoked": False,
        "source": "unknown",
        "updated_at": None,
        "revocation_reason": None,
    }

    try:
        # Best-effort: ensure an NFT badge exists for non-zero tiers
        tier_val = int(rec.get("tier", 0))
        if tier_val > 0:
            ensure_poh_badge(account_id, tier=tier_val)
    except Exception:
        # Never fail the status call because of NFT minting issues.
        pass

    return StatusResp(
        ok=True,
        account_id=account_id,
        tier=int(rec.get("tier", 0)),
        revoked=bool(rec.get("revoked", False)),
        source=rec.get("source"),
        updated_at=rec.get("updated_at"),
        revocation_reason=rec.get("revocation_reason"),
    )


# ----------- Tier-2 Async Verification -----------

@router.post("/t2/submit")
async def t2_submit(body: T2SubmitReq) -> Dict[str, Any]:
    """
    Submit or update a Tier-2 async verification request.

    Called by:
        websdk.t2Submit({ accountId, videos, title, desc })
    """
    acct = (body.account_id or "").strip()
    if not acct:
        raise HTTPException(status_code=400, detail="account_id required")

    _ensure_executor_ledger()
    cfg = get_t2_config()

    # Soft guard: avoid unbounded growth of pending queue.
    queue = get_t2_queue()
    pending = [a for a in queue.values() if a.get("status") == "pending"]
    if len(pending) >= int(cfg.get("max_pending", 128)):
        raise HTTPException(status_code=429, detail="Too many pending Tier-2 applications")

    app = upsert_t2_application(
        account_id=acct,
        videos=body.videos,
        title=body.title,
        desc=body.desc,
    )

    _persist()
    return {
        "ok": True,
        "application": app,
    }


@router.post("/t2/list")
async def t2_list(body: T2ListReq) -> Dict[str, Any]:
    """
    List Tier-2 applications, optionally filtered by status.
    """
    _ensure_executor_ledger()
    queue = get_t2_queue()

    items: List[Dict[str, Any]] = list(queue.values())
    if body.status:
        wanted = str(body.status).lower()
        items = [a for a in items if str(a.get("status", "")).lower() == wanted]

    total = len(items)
    start = max(0, int(body.offset))
    end = max(start, start + int(body.limit))
    page = items[start:end]

    return {
        "ok": True,
        "total": total,
        "items": page,
        "limit": body.limit,
        "offset": body.offset,
    }


@router.post("/t2/item")
async def t2_item(body: T2ItemReq) -> Dict[str, Any]:
    """
    Fetch a single Tier-2 application by account id.
    """
    acct = (body.account_id or "").strip()
    if not acct:
        raise HTTPException(status_code=400, detail="account_id required")

    _ensure_executor_ledger()
    queue = get_t2_queue()
    app = queue.get(acct)
    if not app:
        raise HTTPException(status_code=404, detail="Tier-2 application not found")

    return {
        "ok": True,
        "application": app,
    }


@router.post("/t2/vote")
async def t2_vote(body: T2VoteReq) -> Dict[str, Any]:
    """
    Register a juror vote for a Tier-2 application.

    Called by:
        websdk.t2Vote({ candidateId, jurorId, approve })
    """
    candidate_id = (body.candidate_id or "").strip()
    juror_id = (body.juror_id or "").strip()
    if not candidate_id or not juror_id:
        raise HTTPException(status_code=400, detail="candidate_id and juror_id required")

    _ensure_executor_ledger()

    try:
        app = register_t2_vote(
            candidate_id=candidate_id,
            juror_id=juror_id,
            approve=bool(body.approve),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Tier-2 application not found")

    # When auto-approved, also mint/upgrade badge.
    try:
        if app.get("status") == "approved":
            rec = get_poh_record(candidate_id)
            if rec:
                ensure_poh_badge(candidate_id, tier=int(rec.get("tier", 2)))
    except Exception:
        pass

    _persist()

    return {
        "ok": True,
        "application": app,
    }


@router.post("/t2/config")
async def t2_config(body: T2ConfigReq) -> Dict[str, Any]:
    """
    Get or update Tier-2 configuration.

    If both fields are None, this behaves as a pure "get" call.
    """
    _ensure_executor_ledger()
    if body.required_yes is None and body.max_pending is None:
        cfg = get_t2_config()
    else:
        cfg = update_t2_config(
            required_yes=body.required_yes,
            max_pending=body.max_pending,
        )

    _persist()

    return {
        "ok": True,
        "config": cfg,
    }


# ---------------------------------------------------------------------------
# Admin / manual PoH tier setting (optional)
# ---------------------------------------------------------------------------

class AdminSetTierReq(BaseModel):
    user_id: str
    tier: int = Field(..., ge=0, le=3)
    source: Optional[str] = None


@router.post("/admin/set-tier")
async def admin_set_tier(body: AdminSetTierReq) -> Dict[str, Any]:
    """
    Minimal admin helper to directly set PoH tier from the backend.

    This should be protected by higher-level auth/ACL in production.
    """
    uid = (body.user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id required")

    _ensure_executor_ledger()
    rec = set_poh_tier(uid, body.tier, source=body.source or "admin_set")

    try:
        ensure_poh_badge(uid, tier=rec.get("tier", body.tier))
    except Exception:
        pass

    _persist()
    return {"ok": True, "poh": rec}
