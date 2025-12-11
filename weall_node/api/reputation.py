"""
weall_node/api/reputation.py
---------------------------------
Reputation API + shared helpers.

Ledger layout under executor.ledger["reputation"]:

{
    "scores": {
        "<user_id>": float,
        ...
    },
    "events": [
        {
            "id": str,
            "user_id": str,
            "delta": float,
            "score_after": float,
            "reason": str,
            "source": str,
            "context": dict | None,
            "created_at": int,
        },
        ...
    ],
}
"""

import time
import secrets
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..weall_executor import executor
from .roles import get_effective_profile_for_user

router = APIRouter(tags=["reputation"])


# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _get_rep_state() -> Dict[str, Any]:
    """
    Ensure executor.ledger has a well-formed 'reputation' root.
    """
    state = executor.ledger.setdefault("reputation", {})
    state.setdefault("scores", {})
    state.setdefault("events", [])
    return state


def record_reputation_event(
    user_id: str,
    delta: float,
    reason: str,
    source: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Shared helper that adjusts a user's reputation and records an event.

    This can be imported by other API modules (e.g. disputes.py).
    """
    state = _get_rep_state()
    scores: Dict[str, float] = state["scores"]
    events: List[Dict[str, Any]] = state["events"]

    current_score = float(scores.get(user_id, 0.0))
    new_score = current_score + float(delta)

    scores[user_id] = new_score

    ev = {
        "id": secrets.token_hex(8),
        "user_id": user_id,
        "delta": float(delta),
        "score_after": float(new_score),
        "reason": reason,
        "source": source,
        "context": context or {},
        "created_at": _now(),
    }
    events.append(ev)
    return ev


def _require_rep_admin():
    """
    Require a Tier 3 human (or higher, if future tiers are added) to adjust reputation.
    """
    async def dependency(
        x_weall_user: str = Header(
            ...,
            alias="X-WeAll-User",
            description="WeAll user identifier (e.g. '@handle' or wallet id).",
        )
    ) -> str:
        profile = get_effective_profile_for_user(x_weall_user)
        # Try multiple common attribute names for tier; default to 0 if missing.
        tier = getattr(profile, "tier", None)
        if tier is None:
            tier = getattr(profile, "poh_tier", 0)

        try:
            tier_int = int(tier or 0)
        except Exception:
            tier_int = 0

        if tier_int < 3:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tier 3 is required to adjust reputation.",
            )
        return x_weall_user

    return dependency


RequireRepAdmin = _require_rep_admin()


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


class ReputationEvent(BaseModel):
    id: str
    user_id: str
    delta: float
    score_after: float
    reason: str
    source: str
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: int


class ReputationSummary(BaseModel):
    ok: bool = True
    user: str
    score: float
    recent_events: List[ReputationEvent] = Field(
        default_factory=list,
        description="Most recent events, newest first.",
    )


class ReputationEventsResponse(BaseModel):
    ok: bool = True
    user: str
    events: List[ReputationEvent]
    total_events: int


class ReputationAdjustRequest(BaseModel):
    user_id: str = Field(..., description="User whose reputation we want to adjust.")
    delta: float = Field(..., description="Amount to add (can be negative).")
    reason: str = Field(..., max_length=4000)
    source: str = Field(
        ...,
        description="System source identifier, e.g. 'dispute:case123', 'manual:admin'.",
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional structured context for this adjustment.",
    )
    preview: bool = Field(
        False,
        description="If true, do not persist; just return the would-be score.",
    )


class ReputationAdjustResponse(BaseModel):
    ok: bool = True
    user: str
    score_before: float
    score_after: float
    event: Optional[ReputationEvent] = None
    preview: bool = False


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@router.get("/{user_id}", response_model=ReputationSummary)
def get_reputation(user_id: str) -> ReputationSummary:
    """
    Get current reputation score and a handful of the most recent events.
    """
    state = _get_rep_state()
    scores: Dict[str, float] = state["scores"]
    events: List[Dict[str, Any]] = state["events"]

    score = float(scores.get(user_id, 0.0))

    user_events = [
        ReputationEvent(**ev)
        for ev in events
        if ev.get("user_id") == user_id
    ]
    # Newest first
    user_events.sort(key=lambda e: e.created_at, reverse=True)
    recent = user_events[:50]

    return ReputationSummary(
        ok=True,
        user=user_id,
        score=score,
        recent_events=recent,
    )


@router.get("/{user_id}/events", response_model=ReputationEventsResponse)
def get_reputation_events(
    user_id: str,
    limit: int = Query(
        200,
        ge=1,
        le=1000,
        description="Max number of events to return (newest first).",
    ),
) -> ReputationEventsResponse:
    """
    Get the full event history (or a truncated view) for a user.
    """
    state = _get_rep_state()
    events: List[Dict[str, Any]] = state["events"]

    user_events = [
        ReputationEvent(**ev)
        for ev in events
        if ev.get("user_id") == user_id
    ]
    user_events.sort(key=lambda e: e.created_at, reverse=True)
    limited = user_events[:limit]

    return ReputationEventsResponse(
        ok=True,
        user=user_id,
        events=limited,
        total_events=len(user_events),
    )


@router.post("/adjust", response_model=ReputationAdjustResponse)
def adjust_reputation(
    payload: ReputationAdjustRequest,
    x_weall_user: str = Depends(RequireRepAdmin),
) -> ReputationAdjustResponse:
    """
    Adjust reputation for a user.

    - Requires a Tier 3 human (or higher) caller.
    - If preview=True, does NOT persist the change, only returns the
      hypothetical score_after.
    """
    state = _get_rep_state()
    scores: Dict[str, float] = state["scores"]

    before = float(scores.get(payload.user_id, 0.0))

    if payload.preview:
        after = before + float(payload.delta)
        return ReputationAdjustResponse(
            ok=True,
            user=payload.user_id,
            score_before=before,
            score_after=after,
            event=None,
            preview=True,
        )

    ev_dict = record_reputation_event(
        user_id=payload.user_id,
        delta=payload.delta,
        reason=payload.reason,
        source=payload.source,
        context=payload.context,
    )
    after = float(ev_dict["score_after"])
    ev_model = ReputationEvent(**ev_dict)

    return ReputationAdjustResponse(
        ok=True,
        user=payload.user_id,
        score_before=before,
        score_after=after,
        event=ev_model,
        preview=False,
    )
