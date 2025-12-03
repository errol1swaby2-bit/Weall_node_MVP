"""
weall_node/api/governance.py
--------------------------------------------------
Clean MVP governance module for WeAll Node.
"""

import time
import secrets
from typing import List, Optional, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter()

# ============================================================
# Models
# ============================================================

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
        description="Proposal lifetime in seconds"
    )


class VoteBody(BaseModel):
    voter_id: str
    choice: str


# ============================================================
# Internal helpers
# ============================================================

def _now() -> int:
    return int(time.time())


def _new_id() -> str:
    return f"gov:{_now()}:{secrets.token_hex(4)}"


def _get_state() -> Dict:
    led = getattr(executor, "ledger", None)
    if led is None:
        raise RuntimeError("ledger_not_initialized")

    gov = led.setdefault("governance", {})
    gov.setdefault("proposals", [])
    return gov


def _save():
    try:
        executor.save_state()
    except Exception:
        pass


def _compute_tallies(votes: Dict[str, str]) -> Dict[str, int]:
    counts = {}
    for c in votes.values():
        counts[c] = counts.get(c, 0) + 1
    return counts


def _normalize_handle(v: str) -> str:
    """Normalize email/handle into @localpart."""
    v = (v or "").strip().lower()
    if not v:
        return v
    if "@" in v and not v.startswith("@"):
        return "@" + v.split("@", 1)[0]
    return v


# ============================================================
# Routes
# ============================================================

@router.get("/meta")
def governance_meta():
    """Basic governance info"""
    gov = _get_state()
    return {
        "ok": True,
        "proposal_count": len(gov["proposals"]),
        "defaults": {
            "options": ["yes", "no", "abstain"],
            "duration_sec": 7 * 24 * 3600
        },
    }


@router.get("/proposals")
def list_proposals():
    """Return full list of proposals with tallies."""
    gov = _get_state()
    now = _now()

    out = []
    for p in gov["proposals"]:
        item = dict(p)
        votes = p.get("votes") or {}
        item["tallies"] = _compute_tallies(votes)

        closes_at = p.get("closes_at")
        if p.get("status") == "open" and closes_at and now >= closes_at:
            item["status"] = "closed"

        out.append(item)

    return {"ok": True, "proposals": out}


@router.post("/proposals")
def create_proposal(body: ProposalCreate):
    """Create a new proposal."""
    gov = _get_state()

    created_by = _normalize_handle(body.created_by)
    if not created_by:
        raise HTTPException(status_code=400, detail="created_by_required")

    options = body.options or ["yes", "no", "abstain"]
    options = [o.strip() for o in options if o.strip()]
    if len(options) < 2:
        raise HTTPException(status_code=400, detail="at_least_two_options_required")

    pid = _new_id()
    now = _now()

    proposal = {
        "id": pid,
        "title": body.title.strip(),
        "description": body.description.strip(),
        "created_by": created_by,
        "type": body.type.strip() or "signal",
        "options": options,
        "created_at": now,
        "closes_at": now + body.duration_sec,
        "status": "open",
        "votes": {},  # voter_id → choice
    }

    gov["proposals"].append(proposal)
    _save()

    item = dict(proposal)
    item["tallies"] = _compute_tallies({})
    return {"ok": True, "proposal": item}


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    """Get single proposal."""
    gov = _get_state()
    now = _now()

    for p in gov["proposals"]:
        if p["id"] == proposal_id:
            item = dict(p)
            votes = p.get("votes") or {}
            item["tallies"] = _compute_tallies(votes)

            closes_at = p.get("closes_at")
            if p.get("status") == "open" and now >= closes_at:
                item["status"] = "closed"

            return {"ok": True, "proposal": item}

    raise HTTPException(status_code=404, detail="proposal_not_found")


@router.post("/proposals/{proposal_id}/vote")
def vote_on_proposal(proposal_id: str, body: VoteBody):
    """Cast or update vote."""
    gov = _get_state()

    voter = _normalize_handle(body.voter_id)
    if not voter:
        raise HTTPException(status_code=400, detail="voter_required")

    for p in gov["proposals"]:
        if p["id"] == proposal_id:

            if p["status"] != "open":
                raise HTTPException(status_code=400, detail="proposal_closed")

            options = p.get("options") or []
            if body.choice not in options:
                raise HTTPException(status_code=400, detail="invalid_choice")

            p["votes"][voter] = body.choice
            _save()

            tallies = _compute_tallies(p["votes"])
            return {
                "ok": True,
                "proposal_id": proposal_id,
                "choice": body.choice,
                "tallies": tallies,
            }

    raise HTTPException(status_code=404, detail="proposal_not_found")
