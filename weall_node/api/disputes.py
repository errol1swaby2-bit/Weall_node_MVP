"""
weall_node/api/disputes.py
---------------------------

FastAPI router that exposes the Juror System & Dispute Resolution
backed by weall_runtime.disputes.

This is a thin wrapper layer; it does *not* implement business logic
itself. All rules (Tier-3 + juror opt-in + reputation threshold, vote
aggregation, etc.) live in `weall_node.weall_runtime.disputes`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    # Preferred path: use a shared runtime/ledger if available
    from ..shared_runtime import get_ledger  # type: ignore
except Exception:  # pragma: no cover
    # Fallback for environments/tests where shared_runtime is not wired.
    _LEDGER: Dict[str, Any] = {}

    def get_ledger() -> Dict[str, Any]:
        return _LEDGER

from ..weall_runtime import disputes as rt_disputes

router = APIRouter(prefix="/disputes", tags=["disputes"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DisputeTarget(BaseModel):
    kind: str = Field(..., description="identity | content | governance")
    id: str = Field(..., description="Target id (e.g. post id, user id, proposal id)")
    extra: Dict[str, Any] = Field(default_factory=dict)


class DisputeOpenRequest(BaseModel):
    opened_by: str = Field(..., description="@handle of reporting user")
    case_type: str = Field(
        ...,
        description="identity | content | governance",
    )
    target_kind: str = Field(
        ...,
        description="Usually same as case_type, kept explicit for future extensibility",
    )
    target_id: str = Field(..., description="ID of the thing being disputed")
    reason: str = Field(..., max_length=4000)
    tags: Optional[List[str]] = Field(default=None)
    evidence_cids: Optional[List[str]] = Field(
        default=None,
        description="Optional list of IPFS CIDs with supporting evidence",
    )
    required_jurors: int = Field(
        7,
        ge=1,
        description="Number of jurors assigned to this case",
    )
    min_approvals: Optional[int] = Field(
        default=None,
        description="Minimum approvals needed to uphold; defaults to ceil(required_jurors / 3)",
    )


class DisputeCaseResponse(BaseModel):
    id: str
    case_type: str
    status: str
    opened_by: str
    target: Dict[str, Any]
    reason: str
    tags: List[str]
    evidence_cids: List[str]
    required_jurors: int
    min_approvals: int
    jurors: Dict[str, Any]
    aggregates: Dict[str, Any]
    decision: Optional[Dict[str, Any]]
    created_at: int
    updated_at: int


class AssignJurorsRequest(BaseModel):
    juror_ids: List[str] = Field(
        ...,
        description="List of juror @handles to assign. Each must be Tier-3, opt-in, and meet min reputation.",
        min_items=1,
    )


class JurorVoteRequest(BaseModel):
    juror_id: str = Field(..., description="@handle of the juror casting the vote")
    vote: str = Field(..., description='"uphold" or "reject"')
    reason: str = Field("", max_length=4000)


# ---------------------------------------------------------------------------
# Helper to normalize runtime case -> API response shape
# ---------------------------------------------------------------------------


def _case_to_response(case: Dict[str, Any]) -> DisputeCaseResponse:
    # Fill in defaults defensively in case runtime evolves
    return DisputeCaseResponse(
        id=case.get("id", ""),
        case_type=case.get("case_type", ""),
        status=case.get("status", ""),
        opened_by=case.get("opened_by", ""),
        target=case.get("target") or {},
        reason=case.get("reason", ""),
        tags=list(case.get("tags") or []),
        evidence_cids=list(case.get("evidence_cids") or []),
        required_jurors=int(case.get("required_jurors") or 0),
        min_approvals=int(case.get("min_approvals") or 0),
        jurors=case.get("jurors") or {},
        aggregates=case.get("aggregates") or {},
        decision=case.get("decision"),
        created_at=int(case.get("created_at") or 0),
        updated_at=int(case.get("updated_at") or 0),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/open", response_model=DisputeCaseResponse)
def open_dispute(payload: DisputeOpenRequest) -> DisputeCaseResponse:
    """
    Open a new dispute.

    This is the main entry point for:
    - identity disputes (flags on PoH identity, revocation/recovery),
    - content disputes (posts, comments, uploads),
    - governance disputes (proposal fraud, abuse, etc.).
    """
    ledger = get_ledger()
    try:
        case = rt_disputes.open_dispute(
            ledger=ledger,
            opened_by=payload.opened_by,
            case_type=payload.case_type,
            target_kind=payload.target_kind,
            target_id=payload.target_id,
            reason=payload.reason,
            tags=payload.tags,
            evidence_cids=payload.evidence_cids,
            required_jurors=payload.required_jurors,
            min_approvals=payload.min_approvals,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Attach target.extra if the caller sent any extra metadata
    if isinstance(case.get("target"), dict):
        case["target"].setdefault("extra", {})

    return _case_to_response(case)


@router.get("/case/{case_id}", response_model=DisputeCaseResponse)
def get_case(case_id: str) -> DisputeCaseResponse:
    """
    Fetch a single dispute case by id.
    """
    ledger = get_ledger()
    case = rt_disputes.get_case(ledger, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Dispute case not found")
    return _case_to_response(case)


@router.get("/mine", response_model=List[DisputeCaseResponse])
def list_my_cases(user_id: str) -> List[DisputeCaseResponse]:
    """
    List all disputes opened by the given user.

    In a future version this will be wired to session auth, but for now
    user_id is provided explicitly.
    """
    ledger = get_ledger()
    cases = rt_disputes.list_cases_for_user(ledger, user_id)
    return [_case_to_response(c) for c in cases]


@router.get("/juror", response_model=List[DisputeCaseResponse])
def list_cases_for_juror(juror_id: str) -> List[DisputeCaseResponse]:
    """
    List all disputes where this user is currently assigned as a juror.
    """
    ledger = get_ledger()
    cases = rt_disputes.list_cases_for_juror(ledger, juror_id)
    return [_case_to_response(c) for c in cases]


@router.post("/{case_id}/assign", response_model=DisputeCaseResponse)
def assign_jurors(case_id: str, payload: AssignJurorsRequest) -> DisputeCaseResponse:
    """
    Assign jurors to a case.

    Guardrails enforced in runtime:
    - Case must exist and not be decided.
    - Each juror must be Tier 3, opted-in, and have reputation score
      >= MIN_JUROR_SCORE.
    """
    ledger = get_ledger()
    try:
        case = rt_disputes.assign_jurors(
            ledger=ledger,
            case_id=case_id,
            juror_ids=payload.juror_ids,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Dispute case not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _case_to_response(case)


@router.post("/{case_id}/vote", response_model=DisputeCaseResponse)
def apply_juror_vote(case_id: str, payload: JurorVoteRequest) -> DisputeCaseResponse:
    """
    Apply a juror's vote to a dispute case.

    Runtime guardrails:
    - Case must be in STATUS_AWAITING_VOTES.
    - Juror must already be assigned to the case.
    - vote must be "uphold" or "reject".
    - Once enough votes are in, the case is finalized.
    """
    ledger = get_ledger()
    try:
        case = rt_disputes.apply_juror_vote(
            ledger=ledger,
            case_id=case_id,
            juror_id=payload.juror_id,
            vote=payload.vote,
            reason=payload.reason,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Dispute case not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _case_to_response(case)
