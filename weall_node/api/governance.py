"""
weall_node/api/governance.py
--------------------------------------------------
MVP governance for WeAll Node.

- Stores proposals + votes in executor.ledger["governance"]["proposals"].
- Simple yes/no/abstain-style voting (configurable per proposal).
- Adds optional group scoping + audience gating:

    group_id: optional group/DAO this proposal belongs to
    audience:
        "global"            -> anyone may vote
        "group_members"     -> only members of group_id
        "group_emissaries"  -> only emissaries of group_id

Public API:

    GET  /governance/meta
    GET  /governance/proposals
    POST /governance/proposals
    GET  /governance/proposals/{proposal_id}
    POST /governance/proposals/{proposal_id}/vote
"""

import secrets
import time
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/governance", tags=["governance"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ProposalCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = Field("", max_length=4000)
    created_by: str = Field(..., description="@handle of the proposer")
    type: str = Field("signal")
    options: Optional[List[str]] = None
    duration_sec: int = Field(
        7 * 24 * 3600,
        ge=60,
        le=60 * 60 * 24 * 365,
        description="Proposal lifetime in seconds",
    )
    group_id: Optional[str] = Field(
        default=None,
        description="Optional group id this proposal belongs to.",
    )
    audience: str = Field(
        "global",
        description="Who can vote: global, group_members, group_emissaries",
        pattern="^(global|group_members|group_emissaries)$",
    )


class VoteRequest(BaseModel):
    voter: str = Field(..., description="@handle or PoH id of voter")
    choice: str = Field(..., description="One of the proposal options.")


class Proposal(BaseModel):
    id: str
    title: str
    description: str
    created_by: str
    type: str
    options: List[str]
    created_at: int
    closes_at: int
    status: str
    votes: Dict[str, str]
    tallies: Dict[str, int]
    group_id: Optional[str] = None
    audience: str = "global"


class ProposalListResponse(BaseModel):
    ok: bool
    proposals: List[Proposal]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _root() -> Dict[str, Any]:
    ledger = executor.ledger
    root = ledger.setdefault("governance", {})
    root.setdefault("proposals", {})
    return root


def _proposals() -> Dict[str, Dict[str, Any]]:
    return _root().setdefault("proposals", {})  # type: ignore[return-value]


def _save():
    try:
        executor.save_state()
    except Exception:
        pass


def _serialize(rec: Dict[str, Any]) -> Proposal:
    # Ensure all keys exist and are of the right types.
    options = rec.get("options") or ["yes", "no", "abstain"]
    votes = rec.get("votes") or {}
    tallies = rec.get("tallies") or {}
    group_id = rec.get("group_id")
    audience = rec.get("audience") or "global"

    return Proposal(
        id=str(rec["id"]),
        title=str(rec["title"]),
        description=str(rec.get("description", "")),
        created_by=str(rec.get("created_by", "")),
        type=str(rec.get("type", "signal")),
        options=list(options),
        created_at=int(rec.get("created_at", 0)),
        closes_at=int(rec.get("closes_at", 0)),
        status=str(rec.get("status", "open")),
        votes=dict(votes),
        tallies={str(k): int(v) for k, v in tallies.items()},
        group_id=group_id,
        audience=audience,
    )


def _lookup_group(group_id: str) -> Optional[Dict[str, Any]]:
    """
    Minimal group lookup to avoid importing the whole groups API.

    executor.ledger["groups"] layout (from api.groups):

        {
          "groups": {
            "<group_id>": {...}
          },
          "by_member": {...}
        }
    """
    groups_root = executor.ledger.get("groups") or {}
    gmap = groups_root.get("groups") or {}
    return gmap.get(group_id)


def _check_audience(rec: Dict[str, Any], voter: str) -> None:
    """
    Enforce audience rules for group-scoped proposals.

    - global: anyone may vote
    - group_members: only group members
    - group_emissaries: only group emissaries
    """
    audience = rec.get("audience", "global")
    group_id = rec.get("group_id")

    if audience == "global" or not group_id:
        return

    group = _lookup_group(group_id)
    if not group:
        raise HTTPException(status_code=400, detail="group_not_found_for_proposal")

    voter = str(voter)
    members = {str(m) for m in group.get("members") or []}
    emissaries = {str(e) for e in group.get("emissaries") or []}

    if audience == "group_members":
        if voter not in members:
            raise HTTPException(status_code=403, detail="not_in_group_members")
    elif audience == "group_emissaries":
        if voter not in emissaries:
            raise HTTPException(status_code=403, detail="not_in_group_emissaries")


def _update_status_for_time(rec: Dict[str, Any]) -> None:
    """
    Close proposals whose time has elapsed.
    """
    if rec.get("status") != "open":
        return
    closes_at = int(rec.get("closes_at") or 0)
    if closes_at and int(time.time()) >= closes_at:
        rec["status"] = "closed"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/meta")
def get_meta() -> Dict[str, Any]:
    props = _proposals()
    total = len(props)
    open_count = 0
    closed_count = 0
    now = int(time.time())

    for p in props.values():
        _update_status_for_time(p)
        if p.get("status") == "open":
            open_count += 1
        else:
            closed_count += 1

    return {
        "ok": True,
        "total": total,
        "open": open_count,
        "closed": closed_count,
        "now": now,
    }


@router.get("/proposals", response_model=ProposalListResponse)
def list_proposals(
    status: Optional[str] = None,
    group_id: Optional[str] = None,
) -> ProposalListResponse:
    """
    List proposals.

    Query params:
        status   -> "open" or "closed" (optional)
        group_id -> filter to a specific group (optional)
    """
    props = _proposals()
    out: List[Proposal] = []

    for rec in props.values():
        _update_status_for_time(rec)

        if status and rec.get("status") != status:
            continue
        if group_id and rec.get("group_id") != group_id:
            continue

        out.append(_serialize(rec))

    return ProposalListResponse(ok=True, proposals=out)


@router.get("/proposals/{proposal_id}", response_model=Proposal)
def get_proposal(proposal_id: str) -> Proposal:
    props = _proposals()
    rec = props.get(proposal_id)
    if not rec:
        raise HTTPException(status_code=404, detail="proposal_not_found")

    _update_status_for_time(rec)
    return _serialize(rec)


@router.post("/proposals", response_model=Proposal)
def create_proposal(payload: ProposalCreate) -> Proposal:
    """
    Create a new proposal.

    - options default to ["yes", "no", "abstain"] if omitted.
    - If group_id is provided, we ensure that group exists.
    """
    if payload.group_id:
        if not _lookup_group(payload.group_id):
            raise HTTPException(status_code=400, detail="group_not_found")

    props = _proposals()
    now = int(time.time())
    pid = secrets.token_hex(8)

    options = payload.options or ["yes", "no", "abstain"]
    options = [str(o) for o in options]
    if len(options) == 0:
        raise HTTPException(status_code=400, detail="options_required")

    closes_at = now + int(payload.duration_sec)

    rec: Dict[str, Any] = {
        "id": pid,
        "title": payload.title,
        "description": payload.description,
        "created_by": payload.created_by,
        "type": payload.type,
        "options": options,
        "created_at": now,
        "closes_at": closes_at,
        "status": "open",
        "votes": {},            # voter_id -> option
        "tallies": {o: 0 for o in options},
        "group_id": payload.group_id,
        "audience": payload.audience,
    }

    props[pid] = rec
    _save()
    return _serialize(rec)


@router.post("/proposals/{proposal_id}/vote", response_model=Proposal)
def vote_on_proposal(proposal_id: str, payload: VoteRequest) -> Proposal:
    """
    Cast or change a vote on a proposal.

    - Enforces proposal status (must be open and within time).
    - Enforces group audience rules if group_id/audience are set.
    - One-vote-per-voter semantics; changing vote moves tallies accordingly.
    """
    props = _proposals()
    rec = props.get(proposal_id)
    if not rec:
        raise HTTPException(status_code=404, detail="proposal_not_found")

    _update_status_for_time(rec)
    if rec.get("status") != "open":
        raise HTTPException(status_code=400, detail="proposal_closed")

    choice = payload.choice
    options = rec.get("options") or []
    if choice not in options:
        raise HTTPException(status_code=400, detail="invalid_choice")

    voter = str(payload.voter)

    # Enforce audience rules for group-scoped proposals
    _check_audience(rec, voter)

    votes: Dict[str, str] = rec.setdefault("votes", {})
    tallies: Dict[str, int] = rec.setdefault("tallies", {})

    prev = votes.get(voter)
    if prev == choice:
        # idempotent
        return _serialize(rec)

    # Decrement previous choice
    if prev is not None and prev in tallies:
        tallies[prev] = max(0, int(tallies.get(prev, 0)) - 1)

    # Record new choice
    votes[voter] = choice
    tallies[choice] = int(tallies.get(choice, 0)) + 1

    _save()
    return _serialize(rec)
