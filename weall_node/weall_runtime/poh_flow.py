from __future__ import annotations

"""
weall_node/weall_runtime/poh_flow.py
------------------------------------

Full PoH upgrade pipeline for WeAll.

This module defines:

- The canonical structure of PoH records in the executor ledger.
- The full tier upgrade flows from Tier 0/1 up through Tier 3.
- A state machine for Tier 2 (async video verification) and
  Tier 3 (live juror call plus votes).
- Helpers for expiry and Tier 3 revocation.

This module is *ledger-only*: it does not do any network / IO / media work.
The frontend + orchestrator are responsible for capturing video, scheduling
calls, and choosing jurors. They call into these helpers to mutate state.
"""

from dataclasses import dataclass
import hashlib
import secrets
import time
from typing import Any, Dict, Iterable, List, Optional


# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------

TIER_0 = 0   # observer / unverified
TIER_1 = 1   # email-verified
TIER_2 = 2   # async-video verified
TIER_3 = 3   # live-juror verified


# ---------------------------------------------------------------------------
# Request status values
# ---------------------------------------------------------------------------

STATUS_REQUESTED = "requested"
STATUS_AWAITING_EVIDENCE = "awaiting_evidence"           # Tier 2
STATUS_AWAITING_JUROR_ASSIGNMENT = "awaiting_juror_assignment"  # Tier 3
STATUS_CALL_SCHEDULED = "call_scheduled"                 # Tier 3
STATUS_IN_CALL = "in_call"                               # Tier 3
STATUS_AWAITING_VOTES = "awaiting_votes"                 # Tier 2 & 3
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_REVOKED = "revoked"

ACTIVE_STATUSES = {
    STATUS_REQUESTED,
    STATUS_AWAITING_EVIDENCE,
    STATUS_AWAITING_JUROR_ASSIGNMENT,
    STATUS_CALL_SCHEDULED,
    STATUS_IN_CALL,
    STATUS_AWAITING_VOTES,
}

VOTE_APPROVE = "approve"
VOTE_REJECT = "reject"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _hash_cids(cids: Iterable[str]) -> str:
    """
    Hash a list of IPFS CIDs into a single SHA-256 hex digest.

    We only store hashes of media (not the raw CIDs) in PoH records.
    """
    cleaned = [str(c).strip() for c in cids if c]
    joined = " ".join(sorted(cleaned))
    h = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


# ---------------------------------------------------------------------------
# Dataclasses for clarity (these aren't required to use the module)
# ---------------------------------------------------------------------------


@dataclass
class TierParams:
    request_ttl_sec: int
    required_jurors: int
    min_approvals: int


# ---------------------------------------------------------------------------
# Ledger root helpers
# ---------------------------------------------------------------------------


def _ensure_poh_root(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the PoH root exists in the executor ledger.

    Structure:

        ledger["poh"] = {
            "records": { "<user_id>": { ... } },
            "upgrade_requests": { "<req_id>": { ... } },
            "params": {
                2: { "request_ttl_sec": int, "required_jurors": int, "min_approvals": int },
                3: { "request_ttl_sec": int, "required_jurors": int, "min_approvals": int },
            },
        }
    """
    poh_root = ledger.setdefault("poh", {})
    poh_root.setdefault("records", {})
    poh_root.setdefault("upgrade_requests", {})

    params = poh_root.setdefault("params", {})
    # Defaults aligned with spec spirit; can be overridden at runtime.
    params.setdefault(2, {
        "request_ttl_sec": 3 * 24 * 3600,  # Tier 2: 3 days by default
        "required_jurors": 3,
        "min_approvals": 2,
    })
    params.setdefault(3, {
        "request_ttl_sec": 7 * 24 * 3600,  # Tier 3: 7 days by default
        "required_jurors": 7,
        "min_approvals": 3,
    })

    return poh_root


def _tier_params(ledger: Dict[str, Any], target_tier: int) -> TierParams:
    poh_root = _ensure_poh_root(ledger)
    raw = poh_root["params"].get(target_tier, {})
    return TierParams(
        request_ttl_sec=int(raw.get("request_ttl_sec", 7 * 24 * 3600)),
        required_jurors=int(raw.get("required_jurors", 7)),
        min_approvals=int(raw.get("min_approvals", 3)),
    )


# ---------------------------------------------------------------------------
# PoH record helpers
# ---------------------------------------------------------------------------


def get_poh_record(ledger: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a user's PoH record, or None if it doesn't exist.
    """
    poh_root = _ensure_poh_root(ledger)
    return poh_root["records"].get(user_id)


def ensure_poh_record(ledger: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Ensure a PoH record exists for a given user and return it.

    If it doesn't exist yet, a Tier-0 stub is created.
    """
    poh_root = _ensure_poh_root(ledger)
    records = poh_root["records"]
    rec = records.get(user_id)
    if rec is None:
        rec = {
            "tier": TIER_0,
            "history": [],
            "evidence_hashes": [],
        }
        records[user_id] = rec
    else:
        rec.setdefault("history", [])
        rec.setdefault("evidence_hashes", [])
    return rec


def _append_history(
    rec: Dict[str, Any],
    *,
    new_tier: int,
    reason: str,
    at: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if at is None:
        at = _now()
    entry = {
        "tier": new_tier,
        "at": at,
        "reason": reason,
    }
    if extra:
        entry.update(extra)
    rec["history"].append(entry)


# ---------------------------------------------------------------------------
# Generic upgrade-request helpers
# ---------------------------------------------------------------------------


def _iter_active_requests_for_user(
    ledger: Dict[str, Any],
    user_id: str,
    *,
    target_tier: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    poh_root = _ensure_poh_root(ledger)
    for req in poh_root["upgrade_requests"].values():
        if req.get("user_id") != user_id:
            continue
        if target_tier is not None and req.get("target_tier") != target_tier:
            continue
        if req.get("status") in ACTIVE_STATUSES:
            yield req


def get_active_request_for_user(
    ledger: Dict[str, Any],
    user_id: str,
    *,
    target_tier: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    for req in _iter_active_requests_for_user(ledger, user_id, target_tier=target_tier):
        return req
    return None


def submit_upgrade_request(
    ledger: Dict[str, Any],
    user_id: str,
    target_tier: int,
    *,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """
    Create (or reuse) an upgrade request for a user.

    Rules:
    - target_tier must be 1, 2, or 3.
    - current tier must be < target_tier.
    - For Tier 2, current tier must be 1.
    - For Tier 3, current tier must be 2.
    - At most one active request per user+target_tier.
    """
    if target_tier not in {TIER_1, TIER_2, TIER_3}:
        raise ValueError("target_tier must be 1, 2, or 3")

    rec = ensure_poh_record(ledger, user_id)
    current = int(rec.get("tier", TIER_0))

    if current >= target_tier:
        # Already at or above requested tier; record a no-op for auditing.
        _append_history(
            rec,
            new_tier=current,
            reason="upgrade_request_noop_already_at_or_above_tier",
            extra={"requested_target_tier": target_tier},
        )
        return {
            "id": None,
            "user_id": user_id,
            "current_tier": current,
            "target_tier": target_tier,
            "status": STATUS_APPROVED,
            "auto": True,
            "decided_at": _now(),
            "decision": "noop",
        }

    if target_tier == TIER_2 and current != TIER_1:
        raise ValueError("Tier 2 requires current Tier 1")
    if target_tier == TIER_3 and current != TIER_2:
        raise ValueError("Tier 3 requires current Tier 2")

    # Reuse existing active request if present.
    existing = get_active_request_for_user(ledger, user_id, target_tier=target_tier)
    if existing is not None:
        return existing

    poh_root = _ensure_poh_root(ledger)
    params = _tier_params(ledger, target_tier)
    now = _now()
    req_id = secrets.token_hex(8)

    # Initial status depends on target_tier:
    # - Tier 1: can be auto-approved or handled by email; treat as requested.
    # - Tier 2: awaiting async video evidence.
    # - Tier 3: awaiting juror assignment for live call.
    if target_tier == TIER_1:
        status = STATUS_REQUESTED
    elif target_tier == TIER_2:
        status = STATUS_AWAITING_EVIDENCE
    else:
        status = STATUS_AWAITING_JUROR_ASSIGNMENT

    req = {
        "id": req_id,
        "user_id": user_id,
        "current_tier": current,
        "target_tier": target_tier,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + params.request_ttl_sec,
        "evidence": {},
        "jurors": {},          # juror_id -> juror_info
        "aggregates": {"yes": 0, "no": 0},
        "required_jurors": params.required_jurors,
        "min_approvals": params.min_approvals,
        "call": None,          # For Tier 3 live calls
    }

    poh_root["upgrade_requests"][req_id] = req

    if target_tier == TIER_1 and auto_approve:
        # Some deployments may auto-approve Tier 1 on email verification.
        return _apply_upgrade_to_record(ledger, req, new_tier=TIER_1, reason="tier1_auto_email_verified")

    return req


# ---------------------------------------------------------------------------
# Tier 1 helper
# ---------------------------------------------------------------------------


def approve_tier1_email_verified(
    ledger: Dict[str, Any],
    request_id: str,
    *,
    decided_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Approve a Tier 1 request based on an email-verification pipeline.
    """
    poh_root = _ensure_poh_root(ledger)
    req = poh_root["upgrade_requests"].get(request_id)
    if not req or req.get("target_tier") != TIER_1:
        raise KeyError("tier1_request_not_found")

    return _apply_upgrade_to_record(
        ledger,
        req,
        new_tier=TIER_1,
        reason="tier1_email_verified",
        decided_by=decided_by,
    )


# ---------------------------------------------------------------------------
# Tier 2 (async video) flow
# ---------------------------------------------------------------------------


def submit_tier2_async_video(
    ledger: Dict[str, Any],
    request_id: str,
    user_id: str,
    *,
    video_cids: Optional[List[str]] = None,
    random_phrase: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Attach async video evidence for a Tier 2 request.

    This is the "record yourself reading the random phrase" step.
    """
    poh_root = _ensure_poh_root(ledger)
    reqs = poh_root["upgrade_requests"]
    req = reqs.get(request_id)
    if not req or req.get("target_tier") != TIER_2 or req.get("user_id") != user_id:
        raise KeyError("tier2_request_not_found")

    if req.get("status") not in {STATUS_REQUESTED, STATUS_AWAITING_EVIDENCE}:
        raise ValueError("Tier 2 request is not in a capturable state")

    evidence: Dict[str, Any] = {
        "video_cids": list(video_cids or []),
        "random_phrase": random_phrase or "",
        "device_fingerprint": device_fingerprint or "",
    }
    if extra_metadata:
        evidence["extra"] = dict(extra_metadata)

    req["evidence"] = evidence
    req["status"] = STATUS_AWAITING_VOTES
    req["updated_at"] = _now()
    return req


# ---------------------------------------------------------------------------
# Tier 3 (live call) flow
# ---------------------------------------------------------------------------


def schedule_tier3_call(
    ledger: Dict[str, Any],
    request_id: str,
    *,
    scheduled_for: int,
    session_id: str,
    scheduled_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Attach live-call scheduling metadata for a Tier 3 request.

    Expects:
    - request.status in {awaiting_juror_assignment, awaiting_votes} depending
      on whether jurors were assigned first or call was scheduled first.
    - call: {session_id, scheduled_for, scheduled_by, started_at, ended_at}.
    """
    poh_root = _ensure_poh_root(ledger)
    reqs = poh_root["upgrade_requests"]
    req = reqs.get(request_id)
    if not req or req.get("target_tier") != TIER_3:
        raise KeyError("tier3_request_not_found")

    if req.get("status") not in {
        STATUS_AWAITING_JUROR_ASSIGNMENT,
        STATUS_AWAITING_VOTES,
        STATUS_CALL_SCHEDULED,
    }:
        raise ValueError("Tier 3 request is not in a schedulable state")

    call = req.get("call") or {}
    call.update(
        {
            "session_id": session_id,
            "scheduled_for": int(scheduled_for),
            "scheduled_by": scheduled_by or "system",
            "started_at": None,
            "ended_at": None,
        }
    )
    req["call"] = call
    req["status"] = STATUS_CALL_SCHEDULED
    req["updated_at"] = _now()
    return req


def mark_tier3_call_started(
    ledger: Dict[str, Any],
    request_id: str,
    *,
    started_at: Optional[int] = None,
) -> Dict[str, Any]:
    poh_root = _ensure_poh_root(ledger)
    req = poh_root["upgrade_requests"].get(request_id)
    if not req or req.get("target_tier") != TIER_3:
        raise KeyError("tier3_request_not_found")

    if req.get("status") not in {STATUS_CALL_SCHEDULED, STATUS_IN_CALL}:
        raise ValueError("Tier 3 request is not in a call-startable state")

    call = req.get("call") or {}
    call.setdefault("session_id", "")
    call["started_at"] = int(started_at or _now())
    req["call"] = call
    req["status"] = STATUS_IN_CALL
    req["updated_at"] = _now()
    return req


def mark_tier3_call_ended(
    ledger: Dict[str, Any],
    request_id: str,
    *,
    ended_at: Optional[int] = None,
    recording_cids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    poh_root = _ensure_poh_root(ledger)
    req = poh_root["upgrade_requests"].get(request_id)
    if not req or req.get("target_tier") != TIER_3:
        raise KeyError("tier3_request_not_found")

    if req.get("status") not in {STATUS_IN_CALL, STATUS_CALL_SCHEDULED}:
        raise ValueError("Tier 3 request is not in a call-endable state")

    call = req.get("call") or {}
    call["ended_at"] = int(ended_at or _now())
    if recording_cids:
        call["recording_cids"] = list(recording_cids)
    req["call"] = call
    req["status"] = STATUS_AWAITING_VOTES
    req["updated_at"] = _now()
    return req


# ---------------------------------------------------------------------------
# Juror assignment & voting (shared by Tier 2 and Tier 3)
# ---------------------------------------------------------------------------


def assign_jurors(
    ledger: Dict[str, Any],
    request_id: str,
    juror_ids: Iterable[str],
    *,
    overwrite_existing: bool = False,
) -> Dict[str, Any]:
    """
    Assign jurors to a Tier 2 or Tier 3 request.

    Actual juror *selection* should happen in higher-level orchestration.
    This function only mutates ledger state.
    """
    poh_root = _ensure_poh_root(ledger)
    req = poh_root["upgrade_requests"].get(request_id)
    if not req:
        raise KeyError("upgrade_request_not_found")

    status = req.get("status")
    if status not in {
        STATUS_AWAITING_EVIDENCE,          # Tier 2, evidence not yet attached
        STATUS_AWAITING_JUROR_ASSIGNMENT,  # Tier 3 pre-call
        STATUS_CALL_SCHEDULED,
        STATUS_IN_CALL,
        STATUS_AWAITING_VOTES,
    }:
        raise ValueError("Request not in a juror-assignable state")

    jurors = req.setdefault("jurors", {})
    now = _now()

    if overwrite_existing:
        jurors.clear()

    for j in juror_ids:
        if not j:
            continue
        if j in jurors and not overwrite_existing:
            continue
        jurors[j] = {
            "assigned_at": now,
            "accepted_at": None,
            "vote": None,
            "voted_at": None,
            "reason": "",
        }

    req["updated_at"] = now
    # For Tier 3, if we were waiting for jurors, we stay in that status
    # until the call is explicitly scheduled.
    return req


def apply_juror_vote(
    ledger: Dict[str, Any],
    request_id: str,
    juror_id: str,
    vote: str,
    *,
    reason: str = "",
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Record a juror's vote on a Tier 2 or Tier 3 request and, if thresholds
    are met, apply the upgrade.

    Tier 2:
        - Jurors are voting on async video evidence.
        - Request must be in STATUS_AWAITING_VOTES.

    Tier 3:
        - Jurors are voting after a live call.
        - Request must be in STATUS_AWAITING_VOTES and call.ended_at set.
    """
    if vote not in {VOTE_APPROVE, VOTE_REJECT}:
        raise ValueError("Invalid vote; expected 'approve' or 'reject'")

    if now is None:
        now = _now()

    poh_root = _ensure_poh_root(ledger)
    reqs = poh_root["upgrade_requests"]
    req = reqs.get(request_id)
    if not req:
        raise KeyError("upgrade_request_not_found")

    target_tier = int(req.get("target_tier", 0))
    status = req.get("status")

    if status != STATUS_AWAITING_VOTES:
        raise ValueError("Request is not currently accepting votes")

    if now > int(req.get("expires_at", 0)):
        req["status"] = STATUS_EXPIRED
        req["updated_at"] = now
        return req

    if target_tier == TIER_3:
        call = req.get("call") or {}
        if not call.get("ended_at"):
            raise ValueError("Tier 3 votes can only be cast after call has ended")

    jurors = req.setdefault("jurors", {})
    juror_rec = jurors.get(juror_id)
    if not juror_rec:
        raise ValueError("Juror not assigned to this request")

    aggregates = req.setdefault("aggregates", {"yes": 0, "no": 0})
    yes = int(aggregates.get("yes", 0))
    no = int(aggregates.get("no", 0))

    # Remove prior vote if present.
    prior_vote = juror_rec.get("vote")
    if prior_vote == VOTE_APPROVE:
        yes -= 1
    elif prior_vote == VOTE_REJECT:
        no -= 1

    # Apply new vote.
    if vote == VOTE_APPROVE:
        yes += 1
    else:
        no += 1

    aggregates["yes"] = yes
    aggregates["no"] = no

    juror_rec["vote"] = vote
    juror_rec["voted_at"] = now
    juror_rec["reason"] = reason
    if juror_rec.get("assigned_at") is None:
        juror_rec["assigned_at"] = now

    req["updated_at"] = now

    params = _tier_params(ledger, target_tier)
    total_cast = yes + no

    # Approval rule: at least min_approvals yes, yes > no, and at least
    # min_approvals total votes cast.
    if yes >= params.min_approvals and yes > no and total_cast >= params.min_approvals:
        if target_tier == TIER_2:
            return _apply_upgrade_to_record(
                ledger,
                req,
                new_tier=TIER_2,
                reason="tier2_async_juror_approved",
            )
        elif target_tier == TIER_3:
            return _apply_upgrade_to_record(
                ledger,
                req,
                new_tier=TIER_3,
                reason="tier3_live_juror_approved",
            )

    # Rejection rule: so many "no" votes that it's impossible to reach
    # min_approvals yes votes with remaining jurors.
    if no > (params.required_jurors - params.min_approvals):
        req["status"] = STATUS_REJECTED
        req["decided_at"] = now
        req["decision"] = "rejected_by_jurors"
        return req

    # Otherwise we stay in awaiting_votes.
    return req


# ---------------------------------------------------------------------------
# Upgrade application, expiry, revocation
# ---------------------------------------------------------------------------


def _apply_upgrade_to_record(
    ledger: Dict[str, Any],
    req: Dict[str, Any],
    *,
    new_tier: int,
    reason: str,
    decided_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Internal helper to apply a tier upgrade to the PoH record.
    """
    poh_root = _ensure_poh_root(ledger)
    records = poh_root["records"]

    user_id = req["user_id"]
    rec = records.get(user_id)
    if rec is None:
        rec = {
            "tier": TIER_0,
            "history": [],
            "evidence_hashes": [],
        }
        records[user_id] = rec

    rec.setdefault("history", [])
    rec.setdefault("evidence_hashes", [])

    # Hash any media CIDs we want to bind to this tier.
    hashes: List[str] = []

    # Tier 2: hash async video CIDs.
    if new_tier == TIER_2:
        evidence = req.get("evidence") or {}
        video_cids = evidence.get("video_cids") or []
        if video_cids:
            hashes.append(_hash_cids(video_cids))

    # Tier 3: hash live-call recording CIDs if present.
    if new_tier == TIER_3:
        call = req.get("call") or {}
        rec_cids = call.get("recording_cids") or []
        if rec_cids:
            hashes.append(_hash_cids(rec_cids))

    for h in hashes:
        if h not in rec["evidence_hashes"]:
            rec["evidence_hashes"].append(h)

    # Apply tier upgrade.
    rec["tier"] = new_tier
    now = _now()
    _append_history(
        rec,
        new_tier=new_tier,
        reason=reason,
        at=now,
        extra={"upgrade_request_id": req["id"], "decided_by": decided_by or "system"},
    )

    # Mark request as approved.
    req["status"] = STATUS_APPROVED
    req["decided_at"] = now
    req["updated_at"] = now
    req["decision"] = "approved"
    req["decided_by"] = decided_by or "system"

    return req


def expire_stale_requests(
    ledger: Dict[str, Any],
    *,
    now: Optional[int] = None,
) -> List[str]:
    """
    Mark any active upgrade requests as EXPIRED if their expires_at has passed.

    Returns list of request IDs that were updated.
    """
    if now is None:
        now = _now()

    poh_root = _ensure_poh_root(ledger)
    reqs = poh_root["upgrade_requests"]

    expired_ids: List[str] = []
    for req_id, req in reqs.items():
        if req.get("status") not in ACTIVE_STATUSES:
            continue
        if now > int(req.get("expires_at", 0)):
            req["status"] = STATUS_EXPIRED
            req["expired_at"] = now
            req["updated_at"] = now
            expired_ids.append(req_id)

    return expired_ids


def revoke_tier3(
    ledger: Dict[str, Any],
    user_id: str,
    *,
    reason: str,
    by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Revoke Tier 3 status for a user and append a history entry.

    This does NOT delete evidence or requests; it simply:
    - Records the revocation.
    - Downgrades tier to 2 if they were at 3.
    """
    rec = ensure_poh_record(ledger, user_id)
    prior_tier = int(rec.get("tier", TIER_0))
    now = _now()

    rec.setdefault("history", [])
    rec["history"].append(
        {
            "tier": prior_tier,
            "at": now,
            "reason": "tier3_revoked",
            "detail": reason,
            "by": by or "system",
        }
    )

    if prior_tier >= TIER_3:
        rec["tier"] = TIER_2

    return rec
