from __future__ import annotations

"""
Disputes / juror API for WeAll.

This module provides a minimal but production-leaning implementation of
dispute cases backed by the executor ledger.

Goals:
- Allow the rest of the system (especially /content) to open disputes.
- Randomly select tier-3 jurors using the PoH ledger.
- Expose a small REST surface for listing, inspecting, and resolving cases.
- On decision, reward participating jurors via the "jurors" reward pool,
  bump their reputation, and record optional sanctions for future slashing.
"""

import random
import secrets
import time
from typing import Dict, List, Optional, Any, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor

# Reputation is optional but highly recommended
try:  # pragma: no cover - optional import
    from . import reputation as reputation_api
except Exception:  # pragma: no cover
    reputation_api = None  # type: ignore[assignment]

router = APIRouter(prefix="/disputes", tags=["Disputes"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DisputeCase(BaseModel):
    id: str
    case_type: str
    target_post_id: Optional[str] = None
    target_poh_id: Optional[str] = None
    created_by: str
    reason: str
    description: Optional[str] = None
    status: str
    jurors_live: List[str] = []
    jurors_watch: List[str] = []
    created_at: int
    updated_at: int
    decision: Optional[Dict[str, Any]] = None


class DisputeCaseCreate(BaseModel):
    case_type: str = Field(..., description="e.g. 'content', 'identity', 'recovery', 'other'")
    target_post_id: Optional[str] = Field(
        default=None, description="Post id / cid if this is a content dispute."
    )
    target_poh_id: Optional[str] = Field(
        default=None,
        description="PoH id if this is an identity / recovery dispute.",
    )
    created_by: str = Field(..., description="@handle or PoH id opening the dispute.")
    reason: str = Field(..., max_length=280)
    description: Optional[str] = Field(default=None, max_length=4000)


class DisputeDecisionRequest(BaseModel):
    outcome: str = Field(
        ...,
        description="Application-level outcome. Suggested: 'upheld', 'rejected', 'mixed'.",
    )
    decided_by: str = Field(..., description="@handle or panel identifier.")
    notes: Optional[str] = Field(default=None, max_length=4000)

    # Juror reward settings
    reward_jurors: bool = Field(
        True,
        description="If true, reward live jurors with tickets in the 'jurors' pool.",
    )
    reward_weight: float = Field(
        1.0,
        ge=0.0,
        le=10.0,
        description="Ticket weight per live juror when rewarding.",
    )

    # Optional sanction hook (no actual burn yet)
    sanction_poh_id: Optional[str] = Field(
        default=None,
        description="Optional PoH id to record a sanction for.",
    )
    sanction_level: Optional[str] = Field(
        default=None,
        description="Optional level, e.g. 'warning', 'soft_slash', 'hard_slash'.",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _root() -> Dict[str, Any]:
    ledger = executor.ledger
    root = ledger.setdefault("disputes", {})
    root.setdefault("cases", {})
    root.setdefault("by_target", {})
    return root


def _target_key(case_type: str, target_post_id: Optional[str], target_poh_id: Optional[str]) -> Optional[str]:
    if case_type == "content" and target_post_id:
        return f"content:{target_post_id}"
    if case_type in ("identity", "recovery") and target_poh_id:
        return f"poh:{target_poh_id}"
    return None


def _juror_rewards_root() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ledger = executor.ledger
    root = ledger.setdefault("juror_rewards", {})
    stats = root.setdefault("stats", {})
    return root, stats


def _sanctions_root() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    ledger = executor.ledger
    root = ledger.setdefault("sanctions", {})
    records = root.setdefault("records", [])
    return root, records


def _save():
    try:
        executor.save_state()
    except Exception:
        pass


def _select_tier3_jurors(required: int = 5, exclude: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Very small juror selection helper that reads from executor.ledger["poh"].

    We look for records with tier >= 3 and status == "active". The identity
    we return is the PoH id (record["poh_id"]).
    """
    poh_state = executor.ledger.get("poh") or {}
    records = (poh_state.get("records") or {}).values()

    exclude_set = set(exclude or [])
    candidates: List[str] = []
    for rec in records:
        try:
            if rec.get("tier", 0) >= 3 and rec.get("status", "active") == "active":
                poh_id = rec.get("poh_id")
                if poh_id and poh_id not in exclude_set:
                    candidates.append(poh_id)
        except Exception:
            continue

    if not candidates:
        # No eligible jurors yet; return empty lists but keep the case open.
        return {"jurors_live": [], "jurors_watch": []}

    rng = random.Random(secrets.randbits(64))
    rng.shuffle(candidates)

    required = max(1, min(required, len(candidates)))
    live_n = min(3, required)
    watch_n = max(0, required - live_n)

    chosen = candidates[:required]
    jurors_live = chosen[:live_n]
    jurors_watch = chosen[live_n : live_n + watch_n]
    return {"jurors_live": jurors_live, "jurors_watch": jurors_watch}


def _serialize_case(rec: Dict[str, Any]) -> DisputeCase:
    return DisputeCase(**rec)


def _reward_live_jurors_for_case(case_rec: Dict[str, Any], payload: DisputeDecisionRequest) -> None:
    """
    Reward live jurors for a decided case by:
    - Adding tickets in the 'jurors' pool via executor.wecoin.add_ticket(...)
    - Updating executor.ledger["juror_rewards"]["stats"]
    - Optionally bumping their reputation scores.
    """
    if not payload.reward_jurors:
        return

    jurors = case_rec.get("jurors_live") or []
    if not jurors:
        return

    try:
        weight = float(payload.reward_weight or 0.0)
    except Exception:
        weight = 0.0
    if weight <= 0.0:
        return

    wecoin = getattr(executor, "wecoin", None)
    now = int(time.time())
    root, stats = _juror_rewards_root()

    for j in jurors:
        j_str = str(j)

        # Reward pool ticket
        if wecoin is not None:
            try:
                wecoin.add_ticket("jurors", j_str, weight)
            except Exception:
                # Never break dispute resolution because tokenomics is missing
                pass

        # Local stats
        s = stats.setdefault(j_str, {"cases_participated": 0, "last_case_at": 0})
        s["cases_participated"] += 1
        s["last_case_at"] = now

        # Reputation bump (small, tunable)
        if reputation_api is not None and hasattr(reputation_api, "apply_reputation_event"):
            try:
                reputation_api.apply_reputation_event(
                    j_str,
                    +1.0,
                    reason=f"juror_case:{case_rec.get('id')}",
                    source="disputes",
                    meta={"case_type": case_rec.get("case_type")},
                )
            except Exception:
                # Reputation must never break the core dispute flow
                pass

    root["last_update"] = now


def _maybe_record_sanction(case_id: str, payload: DisputeDecisionRequest) -> None:
    """
    Record a sanction recommendation without directly altering balances.

    This creates a durable record that future upgrades / tools can interpret
    as actual slashing or tier changes. It also nudges reputation downward.
    """
    if not payload.sanction_poh_id or not payload.sanction_level:
        return

    root, records = _sanctions_root()
    now = int(time.time())

    rec = {
        "case_id": case_id,
        "poh_id": payload.sanction_poh_id,
        "level": payload.sanction_level,
        "decided_by": payload.decided_by,
        "notes": payload.notes,
        "timestamp": now,
    }
    records.append(rec)
    root["last_update"] = now

    # Reputation penalty
    if reputation_api is not None and hasattr(reputation_api, "apply_reputation_event"):
        try:
            # Heavier hit than a positive juror bump; tune as needed.
            reputation_api.apply_reputation_event(
                payload.sanction_poh_id,
                -2.0,
                reason=f"sanction:{payload.sanction_level}",
                source="disputes",
                meta={"case_id": case_id},
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public helper for other modules (e.g. api.content)
# ---------------------------------------------------------------------------


def create_dispute_for_content_flag(*, post_id: str, flag: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience helper used by api.content.

    - Creates a 'content' dispute case targeting the given post id.
    - Uses the flag dict to populate reason/description/created_by.
    - Automatically selects a juror panel (if any tier-3 PoH records exist).
    """
    now = int(time.time())
    root = _root()
    cases = root["cases"]

    case_id = secrets.token_hex(8)
    created_by = flag.get("flagged_by") or "unknown"
    reason = flag.get("reason") or "flagged_content"
    description = flag.get("details")

    juror_sel = _select_tier3_jurors(required=5, exclude=[created_by])

    rec: Dict[str, Any] = {
        "id": case_id,
        "case_type": "content",
        "target_post_id": str(post_id),
        "target_poh_id": None,
        "created_by": created_by,
        "reason": reason,
        "description": description,
        "status": "open",
        "jurors_live": juror_sel["jurors_live"],
        "jurors_watch": juror_sel["jurors_watch"],
        "created_at": now,
        "updated_at": now,
        "decision": None,
    }

    cases[case_id] = rec

    key = _target_key("content", post_id=str(post_id), target_poh_id=None)
    if key:
        root["by_target"].setdefault(key, []).append(case_id)

    _save()
    return rec


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/meta")
def get_meta() -> Dict[str, Any]:
    root = _root()
    cases = root["cases"]
    open_cases = sum(1 for c in cases.values() if c.get("status") == "open")
    closed_cases = sum(1 for c in cases.values() if c.get("status") == "closed")
    return {
        "ok": True,
        "total_cases": len(cases),
        "open_cases": open_cases,
        "closed_cases": closed_cases,
    }


@router.get("/cases", response_model=Dict[str, List[DisputeCase]])
def list_cases(status: Optional[str] = None) -> Dict[str, List[DisputeCase]]:
    """
    List dispute cases, optionally filtered by status.
    """
    root = _root()
    cases = root["cases"]
    out: List[DisputeCase] = []
    for rec in cases.values():
        if status and rec.get("status") != status:
            continue
        out.append(_serialize_case(rec))
    return {"cases": out}


@router.get("/cases/{case_id}", response_model=DisputeCase)
def get_case(case_id: str) -> DisputeCase:
    root = _root()
    rec = root["cases"].get(case_id)
    if not rec:
        raise HTTPException(status_code=404, detail="case_not_found")
    return _serialize_case(rec)


@router.post("/cases", response_model=DisputeCase)
def create_case(payload: DisputeCaseCreate) -> DisputeCase:
    """
    Generic dispute case creation endpoint.

    For most user-facing "flag content" flows, api.content will call
    create_dispute_for_content_flag() directly instead of this route.
    """
    now = int(time.time())
    root = _root()
    cases = root["cases"]

    case_id = secrets.token_hex(8)

    juror_sel = _select_tier3_jurors(required=5, exclude=[payload.created_by])

    rec: Dict[str, Any] = {
        "id": case_id,
        "case_type": payload.case_type,
        "target_post_id": payload.target_post_id,
        "target_poh_id": payload.target_poh_id,
        "created_by": payload.created_by,
        "reason": payload.reason,
        "description": payload.description,
        "status": "open",
        "jurors_live": jurors_sel["jurors_live"] if (jurors_sel := juror_sel) else [],
        "jurors_watch": juror_sel["jurors_watch"],
        "created_at": now,
        "updated_at": now,
        "decision": None,
    }

    cases[case_id] = rec
    key = _target_key(payload.case_type, payload.target_post_id, payload.target_poh_id)
    if key:
        root["by_target"].setdefault(key, []).append(case_id)

    _save()
    return _serialize_case(rec)


@router.post("/cases/{case_id}/decision", response_model=DisputeCase)
def decide_case(case_id: str, payload: DisputeDecisionRequest) -> DisputeCase:
    """
    Record a decision for a dispute case and mark it closed.

    Side effects:
    - Reward live jurors with tickets in the 'jurors' pool (if enabled)
      and bump their reputation.
    - Record an optional sanction entry and reputational penalty.
    """
    root = _root()
    rec = root["cases"].get(case_id)
    if not rec:
        raise HTTPException(status_code=404, detail="case_not_found")

    now = int(time.time())
    decision = {
        "outcome": payload.outcome,
        "decided_by": payload.decided_by,
        "notes": payload.notes,
        "decided_at": now,
        "reward_jurors": payload.reward_jurors,
        "reward_weight": float(payload.reward_weight),
        "sanction_poh_id": payload.sanction_poh_id,
        "sanction_level": payload.sanction_level,
    }

    rec["decision"] = decision
    rec["status"] = "closed"
    rec["updated_at"] = now

    # Side effects
    _reward_live_jurors_for_case(rec, payload)
    _maybe_record_sanction(case_id, payload)

    _save()
    return _serialize_case(rec)


@router.get("/juror_rewards")
def get_juror_rewards() -> Dict[str, Any]:
    """
    Return the juror rewards scoreboard (cases participated, last_case_at).
    """
    root, stats = _juror_rewards_root()
    return {"stats": stats, "last_update": root.get("last_update")}


@router.get("/sanctions")
def get_sanctions() -> Dict[str, Any]:
    """
    Return the raw list of recorded sanctions.
    """
    root, records = _sanctions_root()
    return {"records": records, "last_update": root.get("last_update")}
