"""
weall_node/api/poh.py
--------------------------------------------------
Proof-of-Humanity (PoH) tiers and upgrade flow.

Tiers:
    0 - Crawler / exchange (read-only, no account)
    1 - Email verified (like, comment, message)
    2 - Async verified human (create posts, join groups)
    3 - Live jury verified human (full protocol access)

Data layout in executor.ledger["poh"]:
    {
        "records": {
            "<poh_id>": {
                "poh_id": str,
                "tier": int,
                "tier_label": str,
                "status": "active" | "revoked",
                "created_at": int,
                "updated_at": int,
            },
            ...
        },
        "requests": {
            "<request_id>": {
                "id": str,
                "poh_id": str,
                "current_tier": int,
                "target_tier": int,
                "status": "pending" | "approved" | "rejected",
                "evidence_cid": str | None,
                "note": str | None,
                "created_at": int,
                "decided_at": int | None,
                "decided_by": str | None,
                "decision_note": str | None,
            },
            ...
        },
    }
"""

import time
import secrets
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter()

# ---------------------------------------------------------------------
# Tier metadata
# ---------------------------------------------------------------------

POH_TIERS: Dict[int, Dict[str, Any]] = {
    0: {
        "label": "Tier 0 – None",
        "description": "Crawler / exchange read-only access to the chain.",
        "capabilities": [
            "Read public chain data",
        ],
    },
    1: {
        "label": "Tier 1 – Email verified",
        "description": "Email verified account.",
        "capabilities": [
            "Like posts",
            "Comment on posts",
            "Send and receive messages",
        ],
    },
    2: {
        "label": "Tier 2 – Async verified human",
        "description": "Async verification (upload evidence, reviewed by jurors).",
        "capabilities": [
            "Everything from Tier 1",
            "Create public and group posts",
            "Join existing groups",
        ],
    },
    3: {
        "label": "Tier 3 – Live jury verified human",
        "description": "Video / live jury verification.",
        "capabilities": [
            "Everything from Tier 2",
            "Create new groups (governance units)",
            "Opt into juror, node operator, and validator roles",
            "Participate in protocol-level governance",
        ],
    },
}

MAX_TIER = max(POH_TIERS.keys())


# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------

class PohStatusResponse(BaseModel):
    ok: bool = True
    poh_id: str
    tier: int
    tier_label: str
    status: str
    created_at: int
    updated_at: int


class PohRequestCreate(BaseModel):
    target_tier: int = Field(..., ge=1, le=MAX_TIER)
    evidence_cid: Optional[str] = None
    note: Optional[str] = Field(
        None,
        max_length=4000,
        description="Optional human-readable note for this request.",
    )


class PohRequest(BaseModel):
    id: str
    poh_id: str
    current_tier: int
    target_tier: int
    status: str
    evidence_cid: Optional[str] = None
    note: Optional[str] = None
    created_at: int
    decided_at: Optional[int] = None
    decided_by: Optional[str] = None
    decision_note: Optional[str] = None


class RequestDecision(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    note: Optional[str] = Field(
        None,
        max_length=4000,
        description="Optional note explaining the decision.",
    )


class PohMetaResponse(BaseModel):
    ok: bool = True
    tiers: Dict[int, Dict[str, Any]]


class PohRequestsResponse(BaseModel):
    ok: bool = True
    requests: List[PohRequest]


# ---------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------

def _now() -> int:
    return int(time.time())


def _get_poh_state() -> Dict[str, Any]:
    """
    Ensure executor.ledger has a stable "poh" root with
    'records' and 'requests' subdicts.
    """
    state = executor.ledger.setdefault("poh", {})
    state.setdefault("records", {})
    state.setdefault("requests", {})
    return state


def _ensure_record(poh_id: str) -> Dict[str, Any]:
    """
    Ensure a PoH record exists for the given poh_id.

    Default tier is 1 (email verified) for real user accounts.
    Tier 0 is reserved for system / crawler contexts.
    """
    state = _get_poh_state()
    records = state["records"]

    rec = records.get(poh_id)
    if rec is None:
        now = _now()
        tier = 1 if poh_id != "anonymous" else 0
        meta = POH_TIERS.get(tier, POH_TIERS[0])

        rec = {
            "poh_id": poh_id,
            "tier": tier,
            "tier_label": meta["label"],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        records[poh_id] = rec

    return rec


def _recompute_and_persist_tier(poh_id: str) -> Dict[str, Any]:
    """
    Look at the base record tier AND any approved requests for this poh_id.
    Set the record's tier to the maximum approved level.
    """
    state = _get_poh_state()
    records = state["records"]
    requests = state["requests"]

    rec = _ensure_record(poh_id)

    base_tier = int(rec.get("tier", 0))
    max_tier = base_tier

    for req in requests.values():
        if req.get("poh_id") == poh_id and req.get("status") == "approved":
            t = int(req.get("target_tier") or 0)
            if t > max_tier:
                max_tier = t

    if max_tier < 0 or max_tier > MAX_TIER:
        max_tier = min(max(max_tier, 0), MAX_TIER)

    if max_tier != rec.get("tier"):
        meta = POH_TIERS.get(max_tier, POH_TIERS[0])
        rec["tier"] = max_tier
        rec["tier_label"] = meta["label"]
        rec["updated_at"] = _now()

    return rec


def _require_user_header(x_weall_user: Optional[str]) -> str:
    if not x_weall_user:
        raise HTTPException(
            status_code=400,
            detail="Missing X-WeAll-User header for PoH operations.",
        )
    return x_weall_user


# ---------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------

@router.get("/poh/meta", response_model=PohMetaResponse)
def poh_meta() -> PohMetaResponse:
    """
    Expose tier metadata for the frontend.
    """
    return PohMetaResponse(ok=True, tiers=POH_TIERS)


@router.get("/poh/me", response_model=PohStatusResponse)
def poh_me(
    x_weall_user: Optional[str] = Header(default=None, alias="X-WeAll-User"),
) -> PohStatusResponse:
    """
    Return PoH status for the current user.

    - If no record exists, create one (Tier 1 for normal accounts).
    - Always recompute tier from any approved upgrade requests.
    """
    poh_id = _require_user_header(x_weall_user)
    rec = _recompute_and_persist_tier(poh_id)

    return PohStatusResponse(
        ok=True,
        poh_id=rec["poh_id"],
        tier=int(rec["tier"]),
        tier_label=str(rec.get("tier_label", POH_TIERS[int(rec["tier"])]["label"])),
        status=str(rec.get("status", "active")),
        created_at=int(rec.get("created_at", _now())),
        updated_at=int(rec.get("updated_at", _now())),
    )


@router.post("/poh/requests", response_model=dict)
def create_poh_request(
    payload: PohRequestCreate,
    x_weall_user: Optional[str] = Header(default=None, alias="X-WeAll-User"),
):
    """
    User-initiated upgrade request to a higher tier (e.g. Tier 2 or 3).
    """
    poh_id = _require_user_header(x_weall_user)
    state = _get_poh_state()
    records = state["records"]
    requests = state["requests"]

    rec = _ensure_record(poh_id)
    current_tier = int(rec.get("tier", 0))

    if payload.target_tier <= current_tier:
        raise HTTPException(
            status_code=400,
            detail="Target tier must be higher than current tier.",
        )
    if payload.target_tier > MAX_TIER:
        raise HTTPException(
            status_code=400,
            detail=f"Target tier {payload.target_tier} is not supported.",
        )

    req_id = secrets.token_hex(8)
    now = _now()

    req = {
        "id": req_id,
        "poh_id": poh_id,
        "current_tier": current_tier,
        "target_tier": int(payload.target_tier),
        "status": "pending",
        "evidence_cid": payload.evidence_cid,
        "note": payload.note,
        "created_at": now,
        "decided_at": None,
        "decided_by": None,
        "decision_note": None,
    }

    requests[req_id] = req

    return {"ok": True, "request": req}


@router.get("/poh/requests/mine", response_model=PohRequestsResponse)
def my_poh_requests(
    x_weall_user: Optional[str] = Header(default=None, alias="X-WeAll-User"),
) -> PohRequestsResponse:
    """
    List all requests created by the current user.
    """
    poh_id = _require_user_header(x_weall_user)
    state = _get_poh_state()
    requests = state["requests"]

    out: List[PohRequest] = []
    for req in requests.values():
        if req.get("poh_id") == poh_id:
            out.append(PohRequest(**req))

    # Sort newest first for convenience
    out.sort(key=lambda r: r.created_at, reverse=True)

    return PohRequestsResponse(ok=True, requests=out)


@router.get("/poh/requests/pending", response_model=PohRequestsResponse)
def pending_poh_requests(
    target_tier: Optional[int] = Query(
        default=None,
        description="If provided, only show requests for this target tier.",
    ),
):
    """
    Juror / operator view of pending requests.

    (For now, access control is manual: use 'jury:local' or similar in X-WeAll-User
    at the client level; later we can gate it on Tier 3 + juror flag.)
    """
    state = _get_poh_state()
    requests = state["requests"]

    out: List[PohRequest] = []
    for req in requests.values():
        if req.get("status") != "pending":
            continue
        if target_tier is not None and int(req.get("target_tier", 0)) != target_tier:
            continue
        out.append(PohRequest(**req))

    # Newest first
    out.sort(key=lambda r: r.created_at, reverse=True)

    return PohRequestsResponse(ok=True, requests=out)


@router.post("/poh/requests/{request_id}/decision", response_model=dict)
def decide_poh_request(
    request_id: str,
    payload: RequestDecision,
    x_weall_user: Optional[str] = Header(default=None, alias="X-WeAll-User"),
):
    """
    Juror/operator decision on a PoH upgrade request.

    For now, any caller (e.g. 'jury:local') can decide. Later we can
    gate this to Tier 3 + juror pool membership.
    """
    decider = _require_user_header(x_weall_user)
    state = _get_poh_state()
    requests = state["requests"]

    req = requests.get(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="PoH request not found")

    if req.get("status") != "pending":
        # Idempotent-ish behaviour: if we try to decide twice, just return.
        raise HTTPException(status_code=400, detail="Request is already approved")

    now = _now()

    if payload.decision == "approve":
        req["status"] = "approved"
    else:
        req["status"] = "rejected"

    req["decided_at"] = now
    req["decided_by"] = decider
    req["decision_note"] = payload.note

    # IMPORTANT: recompute tier now that we have a new decision.
    poh_id = req.get("poh_id")
    if poh_id:
        _recompute_and_persist_tier(poh_id)

    return {"ok": True, "request": req}
