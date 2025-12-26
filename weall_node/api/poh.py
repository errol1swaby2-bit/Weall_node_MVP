"""
weall_node/api/poh.py
---------------------

HTTP API surface for Proof-of-Humanity (PoH) flows.

This module is a thin wrapper over:

    weall_node.weall_runtime.poh_flow

It exposes:

- /poh/meta
- /poh/me
- /poh/requests/mine
- /poh/requests/juror

- /poh/upgrade/tier2          (async video → Tier 2)
- /poh/upgrade/tier3          (request Tier 3 live-call flow)
- /poh/requests/{id}/tier3/schedule_call
- /poh/requests/{id}/tier3/mark_started
- /poh/requests/{id}/tier3/mark_ended
- /poh/requests/{id}/vote     (juror votes for Tier 2 / Tier 3)

Auth model (MVP):
-----------------
For now, the current user is taken from the "X-WeAll-User" header.
In a production environment this should be wired to the auth session /
token logic in routers/auth_session.py.

Role gating:
------------
Juror voting is gated by the same capabilities as the runtime layer:
only Tier-3 humans with "wants_juror" flag (or equivalent) should be
allowed to vote. In this MVP, we treat flags as default and only gate
by Tier and Capability.SERVE_AS_JUROR.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..weall_runtime import poh_flow
from ..weall_runtime import roles as roles_runtime


router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ledger() -> Dict[str, Any]:
    """
    Access the in-memory ledger from the shared executor.

    This assumes executor.ledger is the canonical state dict used by
    weall_node.weall_runtime.* modules. If that ever changes, this helper
    is the only place that needs updating.
    """
    try:
        return executor.ledger  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise RuntimeError("executor.ledger is not available") from exc


def _get_current_user_id(request: Request) -> str:
    """
    MVP: derive the current user ID from the X-WeAll-User header.

    Example: "@alice", "@errol1swaby2", etc.

    In a production deployment, this should be wired into the
    auth_session router (e.g. session cookies / tokens).
    """
    user_id = request.headers.get("X-WeAll-User")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-WeAll-User header")
    return user_id


def _tier_label(tier: int) -> str:
    if tier <= poh_flow.TIER_0:
        return "observer"
    if tier == poh_flow.TIER_1:
        return "tier1"
    if tier == poh_flow.TIER_2:
        return "tier2"
    if tier >= poh_flow.TIER_3:
        return "tier3"
    return "unknown"


def _serialize_poh_record(user_id: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    tier = int(rec.get("tier", 0))
    history = rec.get("history") or []
    evidence_hashes = rec.get("evidence_hashes") or []
    return {
        "user_id": user_id,
        "tier": tier,
        "tier_label": _tier_label(tier),
        "history": history,
        "evidence_hashes": evidence_hashes,
    }


def _serialize_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert the raw upgrade_request dict into a stable JSON shape.
    """
    return {
        "id": req.get("id"),
        "user_id": req.get("user_id"),
        "current_tier": req.get("current_tier"),
        "target_tier": req.get("target_tier"),
        "status": req.get("status"),
        "created_at": req.get("created_at"),
        "updated_at": req.get("updated_at"),
        "expires_at": req.get("expires_at"),
        "aggregates": req.get("aggregates") or {},
        "required_jurors": req.get("required_jurors"),
        "min_approvals": req.get("min_approvals"),
        "jurors": req.get("jurors") or {},
        "call": req.get("call") or None,
    }


def _get_effective_juror_capability(
    ledger: Dict[str, Any],
    user_id: str,
) -> bool:
    """
    Determine whether a given user currently has juror capability.

    MVP behavior:
    - Map PoH record tier -> PoHTier enum.
    - Assume default HumanRoleFlags() (wants_juror=True would be
      more precise, but flags storage is not yet wired into ledger).
    - Check for Capability.SERVE_AS_JUROR.
    """
    rec = poh_flow.ensure_poh_record(ledger, user_id)
    tier_int = int(rec.get("tier", 0))
    try:
        poh_tier_enum = roles_runtime.PoHTier(tier_int)
    except ValueError:
        poh_tier_enum = roles_runtime.PoHTier.OBSERVER

    flags = roles_runtime.HumanRoleFlags()  # default all wants_* = False
    profile = roles_runtime.compute_effective_role_profile(poh_tier_enum, flags)
    return roles_runtime.Capability.SERVE_AS_JUROR in profile.capabilities


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class PohMeResponse(BaseModel):
    user_id: str
    tier: int
    tier_label: str
    history: List[Dict[str, Any]]
    evidence_hashes: List[str]


class Tier2UpgradeBody(BaseModel):
    video_cids: List[str] = Field(
        default_factory=list,
        description="IPFS CIDs for the async verification video(s).",
    )
    random_phrase: Optional[str] = Field(
        default=None,
        description="Random phrase that the user was asked to read.",
    )
    device_fingerprint: Optional[str] = Field(
        default=None,
        description="Opaque device fingerprint or identifier.",
    )
    extra_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Any extra structured metadata.",
    )


class Tier3ScheduleBody(BaseModel):
    scheduled_for: int = Field(
        ...,
        description="Unix timestamp when the live call is scheduled to occur.",
    )
    session_id: str = Field(
        ...,
        description="Backend / WebRTC session identifier for the live call.",
    )
    scheduled_by: Optional[str] = Field(
        default=None,
        description="User id or 'system' that scheduled the call.",
    )


class Tier3MarkEndedBody(BaseModel):
    recording_cids: Optional[List[str]] = Field(
        default=None,
        description="Optional IPFS CIDs pointing to live-call recording segments.",
    )


class JurorVoteBody(BaseModel):
    # Pydantic v2: `regex=` removed; use `pattern=`
    vote: str = Field(..., pattern=r"^(approve|reject)$")
    reason: Optional[str] = Field(
        default="",
        description="Optional free-text explanation from the juror.",
    )


# ---------------------------------------------------------------------------
# Meta + current user endpoints
# ---------------------------------------------------------------------------


@router.get("/poh/meta")
def get_poh_meta() -> Dict[str, Any]:
    """
    Return human-readable metadata about PoH tiers and roles.
    """
    # These descriptions should mirror the Full Scope spec.
    return {
        "tiers": [
            {
                "id": 0,
                "label": "observer",
                "name": "Observer",
                "description": (
                    "Unverified. Can browse public content where allowed, "
                    "but cannot participate or earn rewards."
                ),
            },
            {
                "id": 1,
                "label": "tier1",
                "name": "Tier 1 – Email Verified",
                "description": (
                    "Email + auth verified account. View-only, can prepare "
                    "their profile and begin the Tier 2 flow."
                ),
            },
            {
                "id": 2,
                "label": "tier2",
                "name": "Tier 2 – Async Video Verified",
                "description": (
                    "Async video verified by human jurors. Can post, comment, "
                    "like, join groups, participate in polls, open disputes, "
                    "and (by default) earn creator rewards."
                ),
            },
            {
                "id": 3,
                "label": "tier3",
                "name": "Tier 3 – Live Juror Verified",
                "description": (
                    "Live call with jurors, followed by verification votes. "
                    "Unlocks juror, validator, operator, and emissary "
                    "functions, and the ability to create groups and "
                    "governance proposals."
                ),
            },
        ]
    }


@router.get("/poh/me", response_model=PohMeResponse)
def get_poh_me(request: Request) -> PohMeResponse:
    """
    Fetch the current user's PoH record and derived tier info.
    """
    user_id = _get_current_user_id(request)
    ledger = _get_ledger()
    rec = poh_flow.ensure_poh_record(ledger, user_id)
    data = _serialize_poh_record(user_id, rec)
    return PohMeResponse(**data)


# ---------------------------------------------------------------------------
# Listing upgrade requests
# ---------------------------------------------------------------------------


@router.get("/poh/requests/mine")
def list_my_poh_requests(request: Request) -> Dict[str, Any]:
    """
    List all PoH upgrade requests belonging to the current user.
    """
    user_id = _get_current_user_id(request)
    ledger = _get_ledger()
    poh_root = poh_flow._ensure_poh_root(ledger)  # type: ignore[attr-defined]
    reqs = [
        _serialize_request(req)
        for req in poh_root["upgrade_requests"].values()
        if req.get("user_id") == user_id
    ]
    return {"ok": True, "requests": reqs}


@router.get("/poh/requests/juror")
def list_juror_assignments(request: Request) -> Dict[str, Any]:
    """
    List all upgrade requests where the current user is an assigned juror.
    """
    user_id = _get_current_user_id(request)
    ledger = _get_ledger()
    poh_root = poh_flow._ensure_poh_root(ledger)  # type: ignore[attr-defined]

    assignments: List[Dict[str, Any]] = []
    for req in poh_root["upgrade_requests"].values():
        jurors = req.get("jurors") or {}
        if user_id not in jurors:
            continue
        assignments.append(_serialize_request(req))

    return {"ok": True, "requests": assignments}


# ---------------------------------------------------------------------------
# Tier 2: async video flow
# ---------------------------------------------------------------------------


@router.post("/poh/upgrade/tier2")
def upgrade_to_tier2(body: Tier2UpgradeBody, request: Request) -> Dict[str, Any]:
    """
    Initiate or continue the Tier 2 async video flow for the current user.
    """
    user_id = _get_current_user_id(request)
    ledger = _get_ledger()

    try:
        req = poh_flow.submit_upgrade_request(
            ledger,
            user_id,
            target_tier=poh_flow.TIER_2,
        )
        req = poh_flow.submit_tier2_async_video(
            ledger,
            req["id"],
            user_id,
            video_cids=body.video_cids,
            random_phrase=body.random_phrase,
            device_fingerprint=body.device_fingerprint,
            extra_metadata=body.extra_metadata,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "request": _serialize_request(req)}


# ---------------------------------------------------------------------------
# Tier 3: live call flow
# ---------------------------------------------------------------------------


@router.post("/poh/upgrade/tier3")
def request_tier3_upgrade(request: Request) -> Dict[str, Any]:
    """
    Create (or reuse) a Tier 3 upgrade request for the current user.
    """
    user_id = _get_current_user_id(request)
    ledger = _get_ledger()

    try:
        req = poh_flow.submit_upgrade_request(
            ledger,
            user_id,
            target_tier=poh_flow.TIER_3,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "request": _serialize_request(req)}


@router.post("/poh/requests/{request_id}/tier3/schedule_call")
def schedule_tier3_call(
    request_id: str,
    body: Tier3ScheduleBody,
    request: Request,
) -> Dict[str, Any]:
    """
    Attach live-call scheduling metadata for a Tier 3 request.
    """
    _ = _get_current_user_id(request)  # reserved for auth, currently unused
    ledger = _get_ledger()

    try:
        req = poh_flow.schedule_tier3_call(
            ledger,
            request_id,
            scheduled_for=body.scheduled_for,
            session_id=body.session_id,
            scheduled_by=body.scheduled_by,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "request": _serialize_request(req)}


@router.post("/poh/requests/{request_id}/tier3/mark_started")
def mark_tier3_call_started(
    request_id: str,
    request: Request,
) -> Dict[str, Any]:
    """
    Mark a Tier 3 live call as started.
    """
    _ = _get_current_user_id(request)  # reserved for auth, currently unused
    ledger = _get_ledger()

    try:
        req = poh_flow.mark_tier3_call_started(ledger, request_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "request": _serialize_request(req)}


@router.post("/poh/requests/{request_id}/tier3/mark_ended")
def mark_tier3_call_ended(
    request_id: str,
    body: Tier3MarkEndedBody,
    request: Request,
) -> Dict[str, Any]:
    """
    Mark a Tier 3 live call as ended and optionally attach recording CIDs.
    """
    _ = _get_current_user_id(request)  # reserved for auth, currently unused
    ledger = _get_ledger()

    try:
        req = poh_flow.mark_tier3_call_ended(
            ledger,
            request_id,
            recording_cids=body.recording_cids,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "request": _serialize_request(req)}


# ---------------------------------------------------------------------------
# Juror voting
# ---------------------------------------------------------------------------


@router.post("/poh/requests/{request_id}/vote")
def juror_vote_on_poh_request(
    request_id: str,
    body: JurorVoteBody,
    request: Request,
) -> Dict[str, Any]:
    """
    Apply a juror's vote on a Tier 2 or Tier 3 PoH upgrade request.
    """
    user_id = _get_current_user_id(request)
    ledger = _get_ledger()

    if not _get_effective_juror_capability(ledger, user_id):
        raise HTTPException(status_code=403, detail="User is not authorized to serve as juror")

    try:
        req = poh_flow.apply_juror_vote(
            ledger,
            request_id,
            user_id,
            vote=body.vote,
            reason=body.reason or "",
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "request": _serialize_request(req)}



# --- FLIP CONTROL: PoH ceremony orchestration + genesis params ---
# Goal:
# - Let the network run the "real world" Tier-3 PoH ceremony from the web UI.
# - In genesis, allow a single-verifier mode by setting PoH params:
#     required_jurors=1, min_approvals=1
# - Later, flip to k-of-n by governance param change.

from fastapi import Header
from pydantic import BaseModel
from weall_node.weall_executor import executor
from weall_node.weall_runtime import poh_flow

def _genesis_enabled() -> bool:
    v = (os.getenv("WEALL_GENESIS_MODE") or "").strip().lower()
    return v in ("1","true","yes","on")

def _genesis_admin_user() -> str:
    return (os.getenv("WEALL_GENESIS_ADMIN_USER") or "@genesis").strip()

def _require_genesis_admin(request: Request) -> str:
    uid = _current_user(request)
    if not _genesis_enabled():
        raise HTTPException(status_code=403, detail="Genesis mode disabled")
    if uid != _genesis_admin_user():
        raise HTTPException(status_code=403, detail="Genesis admin only")
    return uid

class PoHParamsSetRequest(BaseModel):
    tier: int = 3
    required_jurors: int = 1
    min_approvals: int = 1
    request_ttl_sec: int | None = None

@router.post("/genesis/set_poh_params", response_model=dict)
def genesis_set_poh_params(body: PoHParamsSetRequest, request: Request):
    """
    Genesis-only: set PoH tier params in-ledger.
    This is the "single verifier" bootstrap lever.
    """
    _require_genesis_admin(request)
    tier = int(body.tier)
    if tier not in (2,3):
        raise HTTPException(status_code=400, detail="tier must be 2 or 3")
    if body.required_jurors < 1 or body.min_approvals < 1:
        raise HTTPException(status_code=400, detail="required_jurors/min_approvals must be >= 1")
    if body.min_approvals > body.required_jurors:
        raise HTTPException(status_code=400, detail="min_approvals cannot exceed required_jurors")

    poh_root = executor.ledger.setdefault("poh", {})
    params = poh_root.setdefault("params", {})
    cur = params.setdefault(tier, {})
    cur["required_jurors"] = int(body.required_jurors)
    cur["min_approvals"] = int(body.min_approvals)
    if body.request_ttl_sec is not None:
        cur["request_ttl_sec"] = int(body.request_ttl_sec)

    return {"ok": True, "tier": tier, "params": cur}

# -----------------------------
# Ceremony orchestration endpoints
# -----------------------------

class AssignJurorsBody(BaseModel):
    juror_ids: list[str]
    overwrite_existing: bool = False

@router.post("/requests/{request_id}/assign_jurors", response_model=dict)
def assign_jurors_api(request_id: str, body: AssignJurorsBody, request: Request):
    """
    Assign jurors to a PoH upgrade request.
    In early days you can assign yourself as the only juror when required_jurors=1.
    """
    user = _current_user(request)
    # Keep policy simple: Tier-3 users can operate PoH flow in early network.
    # (Later we can restrict this to emissaries/operators.)
    rec = get_poh_record(user) or {"tier": 0}
    if int(rec.get("tier", 0) or 0) < 3:
        raise HTTPException(status_code=403, detail="Tier-3 required to assign jurors")

    try:
        out = poh_flow.assign_jurors(executor.ledger, request_id, body.juror_ids, overwrite_existing=bool(body.overwrite_existing))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "request": out}

class ScheduleCallBody(BaseModel):
    scheduled_for: int
    session_id: str
    scheduled_by: str | None = None

@router.post("/requests/{request_id}/schedule_call", response_model=dict)
def schedule_call_api(request_id: str, body: ScheduleCallBody, request: Request):
    user = _current_user(request)
    rec = get_poh_record(user) or {"tier": 0}
    if int(rec.get("tier", 0) or 0) < 3:
        raise HTTPException(status_code=403, detail="Tier-3 required")

    try:
        out = poh_flow.schedule_tier3_call(
            executor.ledger,
            request_id,
            scheduled_for=int(body.scheduled_for),
            session_id=str(body.session_id),
            scheduled_by=body.scheduled_by or user,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "request": out}

@router.post("/requests/{request_id}/call_started", response_model=dict)
def call_started_api(request_id: str, request: Request):
    user = _current_user(request)
    rec = get_poh_record(user) or {"tier": 0}
    if int(rec.get("tier", 0) or 0) < 3:
        raise HTTPException(status_code=403, detail="Tier-3 required")
    try:
        out = poh_flow.mark_tier3_call_started(executor.ledger, request_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "request": out}

class CallEndedBody(BaseModel):
    recording_cids: list[str] | None = None

@router.post("/requests/{request_id}/call_ended", response_model=dict)
def call_ended_api(request_id: str, body: CallEndedBody, request: Request):
    user = _current_user(request)
    rec = get_poh_record(user) or {"tier": 0}
    if int(rec.get("tier", 0) or 0) < 3:
        raise HTTPException(status_code=403, detail="Tier-3 required")
    try:
        out = poh_flow.mark_tier3_call_ended(executor.ledger, request_id, recording_cids=(body.recording_cids or None))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "request": out}

class JurorVoteBody(BaseModel):
    vote: str  # "approve" | "reject"
    reason: str | None = ""

@router.post("/requests/{request_id}/juror_vote", response_model=dict)
def juror_vote_api(request_id: str, body: JurorVoteBody, request: Request):
    juror = _current_user(request)
    rec = get_poh_record(juror) or {"tier": 0}
    if int(rec.get("tier", 0) or 0) < 3:
        raise HTTPException(status_code=403, detail="Tier-3 required")

    try:
        out = poh_flow.apply_juror_vote(
            executor.ledger,
            request_id,
            juror_id=juror,
            vote=str(body.vote),
            reason=str(body.reason or ""),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "request": out}

