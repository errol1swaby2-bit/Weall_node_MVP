"""
weall_node/api/governance.py
--------------------------------------------------
Clean MVP governance module for WeAll Node, with role gating.

Implements proposals and voting as described in the Full Scope:

    - Tier 3 humans (with appropriate roles) can create proposals.
    - Tier 2+ humans can vote.
    - Proposals can be scoped to the global network or a specific group.

JSON shape is intentionally kept compatible with the existing
frontend example:

    {
      "id": "4c0d20099a00fd35",
      "title": "Hello",
      "description": "Yup",
      "created_by": "@errol1swaby2",
      "type": "signal",
      "options": ["yes", "no", "abstain"],
      "created_at": 1764976536,
      "closes_at": 1765581336,
      "status": "open",
      "votes": {
        "@errol1swaby2": "yes"
      },
      "tallies": {
        "yes": 1
      }
    }
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..weall_runtime import roles as runtime_roles

router = APIRouter()


# ============================================================
# Ledger helpers
# ============================================================

def _gov_state() -> Dict[str, Any]:
    return executor.ledger.setdefault("governance", {"proposals": {}})


def _proposals() -> Dict[str, Dict[str, Any]]:
    st = _gov_state()
    return st.setdefault("proposals", {})


def _lookup_poh_record(user_id: str) -> Optional[dict]:
    poh_root = executor.ledger.setdefault("poh", {})
    records = poh_root.setdefault("records", {})
    return records.get(user_id)


def _extract_flags_from_record(record: dict) -> runtime_roles.HumanRoleFlags:
    flags = record.get("flags") or {}
    return runtime_roles.HumanRoleFlags(
        wants_juror=bool(flags.get("wants_juror", False)),
        wants_validator=bool(flags.get("wants_validator", False)),
        wants_operator=bool(flags.get("wants_operator", False)),
        wants_emissary=bool(flags.get("wants_emissary", False)),
        wants_creator=bool(flags.get("wants_creator", True)),
    )


def _effective_profile(user_id: str) -> runtime_roles.EffectiveRoleProfile:
    rec = _lookup_poh_record(user_id)
    if not rec:
        return runtime_roles.compute_effective_role_profile(
            poh_tier=int(runtime_roles.PoHTier.OBSERVER),
            flags=runtime_roles.HumanRoleFlags(
                wants_creator=False,
                wants_juror=False,
                wants_validator=False,
                wants_operator=False,
                wants_emissary=False,
            ),
        )

    tier = int(rec.get("tier", 0))
    flags = _extract_flags_from_record(rec)
    return runtime_roles.compute_effective_role_profile(tier, flags)


def _require_profile_with_cap(
    capability: runtime_roles.Capability,
):
    """
    Factory returning a FastAPI dependency that both:
        - Ensures a valid X-WeAll-User header is present
        - Ensures the effective role profile contains the given capability
    """

    async def dependency(
        x_weall_user: str = Header(
            ...,
            alias="X-WeAll-User",
            description="WeAll user identifier (e.g. '@handle' or wallet id).",
        )
    ) -> str:
        profile = _effective_profile(x_weall_user)
        if capability not in profile.capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required capability: {capability.value}",
            )
        return x_weall_user

    return dependency


# ============================================================
# Models
# ============================================================

class ProposalCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = Field("", max_length=4000)
    created_by: str = Field(..., description="@handle of the proposer")
    type: str = Field("signal", description="Type: 'signal', 'param_change', etc.")
    options: Optional[List[str]] = Field(
        default=None,
        description="Options for voting; default ['yes','no','abstain']",
    )
    duration_sec: int = Field(
        7 * 24 * 3600,
        ge=60,
        le=60 * 60 * 24 * 365,
        description="Proposal lifetime in seconds",
    )
    group_id: Optional[str] = Field(
        default=None,
        description="Optional group this proposal is scoped to.",
    )
    audience: str = Field(
        default="global",
        description=(
            "Who is allowed to vote: 'global', 'group_members', 'group_emissaries'. "
            "For now, this is informational only; a later pass can enforce group scope."
        ),
    )


class Proposal(BaseModel):
    id: str
    title: str
    description: str
    created_by: str
    type: str
    options: List[str]
    created_at: float
    closes_at: float
    status: str
    group_id: Optional[str] = None
    audience: str = "global"
    votes: Dict[str, str]
    tallies: Dict[str, int]


class ProposalsListResponse(BaseModel):
    ok: bool = True
    proposals: List[Proposal]


class ProposalSingleResponse(BaseModel):
    ok: bool = True
    proposal: Proposal


class ProposalVoteRequest(BaseModel):
    choice: str = Field(..., description="One of the proposal's options.")


# ============================================================
# Routes
# ============================================================

@router.get("/proposals", response_model=ProposalsListResponse)
def list_proposals() -> Dict[str, Any]:
    """
    Public, read-only view of all proposals.
    """
    props = _proposals()
    return {
        "ok": True,
        "proposals": [Proposal(**p) for p in props.values()],
    }


@router.get("/proposals/{proposal_id}", response_model=ProposalSingleResponse)
def get_proposal(proposal_id: str) -> Dict[str, Any]:
    props = _proposals()
    if proposal_id not in props:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"ok": True, "proposal": Proposal(**props[proposal_id])}


@router.post(
    "/proposals",
    response_model=ProposalSingleResponse,
)
def create_proposal(
    payload: ProposalCreate,
    proposer_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.CREATE_GOVERNANCE_PROPOSAL)
    ),
) -> Dict[str, Any]:
    """
    Create a new governance proposal.

    Requirements:

        - Caller must have CREATE_GOVERNANCE_PROPOSAL capability
          (Tier 3 + appropriate role flags).
        - created_by in payload must match X-WeAll-User, to prevent spoofing.
    """
    if payload.created_by != proposer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="created_by must match the authenticated user",
        )

    props = _proposals()
    prop_id = secrets.token_hex(8)
    now = time.time()
    closes_at = now + payload.duration_sec

    options = payload.options or ["yes", "no", "abstain"]

    proposal = Proposal(
        id=prop_id,
        title=payload.title,
        description=payload.description,
        created_by=payload.created_by,
        type=payload.type,
        options=options,
        created_at=now,
        closes_at=closes_at,
        status="open",
        group_id=payload.group_id,
        audience=payload.audience,
        votes={},
        tallies={opt: 0 for opt in options},
    ).dict()

    props[prop_id] = proposal

    return {"ok": True, "proposal": Proposal(**proposal)}


@router.post(
    "/proposals/{proposal_id}/vote",
    response_model=ProposalSingleResponse,
)
def vote_proposal(
    proposal_id: str,
    payload: ProposalVoteRequest,
    voter_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.VOTE_GOVERNANCE)
    ),
) -> Dict[str, Any]:
    """
    Cast a vote on a proposal.

    Requirements:

        - Caller must have VOTE_GOVERNANCE capability (Tier 2+).
        - Choice must be one of the proposal's options.
    """
    props = _proposals()
    if proposal_id not in props:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = props[proposal_id]

    if proposal.get("status") != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Proposal is not open for voting",
        )

    choice = payload.choice
    options = proposal.get("options", [])
    if choice not in options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Choice '{choice}' is not a valid option",
        )

    # Record vote
    votes = proposal.setdefault("votes", {})
    tallies = proposal.setdefault("tallies", {opt: 0 for opt in options})

    # If the user has already voted, decrement their previous choice
    prev_choice = votes.get(voter_id)
    if prev_choice is not None and prev_choice in tallies:
        tallies[prev_choice] = max(0, tallies.get(prev_choice, 0) - 1)

    votes[voter_id] = choice
    tallies[choice] = tallies.get(choice, 0) + 1

    props[proposal_id] = proposal

    return {"ok": True, "proposal": Proposal(**proposal)}


@router.post(
    "/proposals/{proposal_id}/close",
    response_model=ProposalSingleResponse,
)
def close_proposal(
    proposal_id: str,
    _closer_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.CREATE_GOVERNANCE_PROPOSAL)
    ),
) -> Dict[str, Any]:
    """
    Manually close a proposal.

    For now, any user who can *create* proposals can also close them.
    Later we can refine this to:
        - automatic close on `closes_at`, and/or
        - special governance roles, and/or
        - proposal-type-specific close logic.
    """
    props = _proposals()
    if proposal_id not in props:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = props[proposal_id]
    proposal["status"] = "closed"
    props[proposal_id] = proposal

    return {"ok": True, "proposal": Proposal(**proposal)}
