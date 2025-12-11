"""
weall_node/weall_runtime/disputes.py
------------------------------------

Runtime logic for the Juror System & Dispute Resolution.

Dispute data lives under:

    ledger["disputes"]["cases"][case_id] = { ... }

Juror eligibility is backed by PoH + reputation:

    ledger["reputation"]["jurors"][user_id] = {
        "score": int,
        "opt_in": bool,
        "strikes": int,
    }

The rules here are intentionally MVP but are structured so we can
later make them more sophisticated without changing the overall
shapes seen by the API.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from . import poh_flow

CASE_TYPE_IDENTITY = "identity"
CASE_TYPE_CONTENT = "content"
CASE_TYPE_GOVERNANCE = "governance"

VALID_CASE_TYPES = {
    CASE_TYPE_IDENTITY,
    CASE_TYPE_CONTENT,
    CASE_TYPE_GOVERNANCE,
}

STATUS_AWAITING_JURORS = "awaiting_jurors"
STATUS_AWAITING_VOTES = "awaiting_votes"
STATUS_DECIDED = "decided"

VOTE_UPHOLD = "uphold"
VOTE_REJECT = "reject"

VALID_VOTES = {VOTE_UPHOLD, VOTE_REJECT}

# Simple MVP threshold; can later be made configurable.
MIN_JUROR_SCORE = 10


# ---------------------------------------------------------------------------
# Root helpers
# ---------------------------------------------------------------------------


def _ensure_disputes_root(ledger: Dict[str, Any]) -> Dict[str, Any]:
    root = ledger.setdefault("disputes", {})
    root.setdefault("cases", {})
    return root


def _timestamp() -> int:
    return int(time.time())


def _new_case_id() -> str:
    return secrets.token_hex(8)


# ---------------------------------------------------------------------------
# Reputation / juror profile helpers
# ---------------------------------------------------------------------------


def _ensure_reputation_root(ledger: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the reputation root exists:

        ledger["reputation"] = {
            "jurors": {
                "@alice": {
                    "score": 0,
                    "opt_in": False,
                    "strikes": 0,
                },
                ...
            }
        }
    """
    rep_root = ledger.setdefault("reputation", {})
    jurors = rep_root.setdefault("jurors", {})
    return jurors


def _ensure_juror_profile(ledger: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Get or create the juror profile record for a user_id.

    We keep it intentionally minimal in the MVP:

        {
            "score": int,
            "opt_in": bool,
            "strikes": int,
        }
    """
    jurors = _ensure_reputation_root(ledger)
    profile = jurors.get(user_id)
    if profile is None:
        profile = {
            "score": 0,
            "opt_in": False,
            "strikes": 0,
        }
        jurors[user_id] = profile
    else:
        profile.setdefault("score", 0)
        profile.setdefault("opt_in", False)
        profile.setdefault("strikes", 0)
    return profile


def set_juror_opt_in(ledger: Dict[str, Any], user_id: str, wants: bool = True) -> Dict[str, Any]:
    """
    Toggle the user's juror-duty opt-in flag.

    Called from profile UI / API when user flips "I want to serve as a juror".
    """
    profile = _ensure_juror_profile(ledger, user_id)
    profile["opt_in"] = bool(wants)
    return profile


def set_juror_score(ledger: Dict[str, Any], user_id: str, score: int) -> Dict[str, Any]:
    """
    Set the juror reputation score for a user.

    In a fuller build, this would be driven by the reputation engine
    (completed cases, reliability, strikes, etc). Here we expose it so
    tests and higher-level modules can apply a threshold.
    """
    profile = _ensure_juror_profile(ledger, user_id)
    profile["score"] = int(score)
    return profile


def set_juror_strikes(ledger: Dict[str, Any], user_id: str, strikes: int) -> Dict[str, Any]:
    """
    Set the juror strike count for a user.

    Each strike represents a no-show or misbehavior on juror duty.
    """
    profile = _ensure_juror_profile(ledger, user_id)
    profile["strikes"] = int(strikes)
    return profile


def get_juror_profile(ledger: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Return the juror profile record for a user_id (creating it if needed).
    """
    return _ensure_juror_profile(ledger, user_id)


def _has_juror_capability(ledger: Dict[str, Any], user_id: str) -> bool:
    """
    Determine whether a user is *currently* eligible to serve as a juror.

    MVP rules:
    - User must be Proof-of-Humanity Tier 3.
    - User must have opt_in == True.
    - User's reputation score must be >= MIN_JUROR_SCORE.
    - User's strikes must be < 3 (soft limit).
    """
    rec = poh_flow.ensure_poh_record(ledger, user_id)
    if rec.get("tier") != poh_flow.TIER_3:
        return False

    profile = _ensure_juror_profile(ledger, user_id)

    if not profile.get("opt_in"):
        return False

    if profile.get("score", 0) < MIN_JUROR_SCORE:
        return False

    if profile.get("strikes", 0) >= 3:
        return False

    return True


def list_eligible_jurors(ledger: Dict[str, Any]) -> List[str]:
    """
    Return a list of user_ids that *currently* satisfy juror eligibility.
    """
    rep_root = _ensure_reputation_root(ledger)
    result: List[str] = []
    for user_id in rep_root.keys():
        if _has_juror_capability(ledger, user_id):
            result.append(user_id)
    return result


# ---------------------------------------------------------------------------
# Dispute lifecycle
# ---------------------------------------------------------------------------


def open_dispute(
    ledger: Dict[str, Any],
    opened_by: str,
    case_type: str,
    target_kind: str,
    target_id: str,
    reason: str,
    tags: Optional[List[str]] = None,
    evidence_cids: Optional[List[str]] = None,
    required_jurors: int = 7,
    min_approvals: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Open a new dispute case and store it in the ledger.

    Rules:
    - case_type must be one of VALID_CASE_TYPES.
    - target_kind is usually the same as case_type, but is kept explicit.
    - required_jurors >= 1.
    - min_approvals defaults to ceil(required_jurors / 3) if not provided.
    """
    if case_type not in VALID_CASE_TYPES:
        raise ValueError(f"Invalid case_type: {case_type}")

    if required_jurors < 1:
        raise ValueError("required_jurors must be >= 1")

    if min_approvals is None:
        # 1/3 of panel, rounded up
        min_approvals = max(1, (required_jurors + 2) // 3)

    now = _timestamp()
    root = _ensure_disputes_root(ledger)
    cases = root["cases"]

    case_id = _new_case_id()

    case = {
        "id": case_id,
        "case_type": case_type,
        "status": STATUS_AWAITING_JURORS,
        "opened_by": opened_by,
        "target": {
            "kind": target_kind,
            "id": target_id,
            "extra": {},
        },
        "reason": reason,
        "tags": list(tags or []),
        "evidence_cids": list(evidence_cids or []),
        "required_jurors": int(required_jurors),
        "min_approvals": int(min_approvals),
        "jurors": {},
        "aggregates": {
            "vote_counts": {
                VOTE_UPHOLD: 0,
                VOTE_REJECT: 0,
            }
        },
        "decision": None,
        "created_at": now,
        "updated_at": now,
    }

    cases[case_id] = case
    return case


def get_case(ledger: Dict[str, Any], case_id: str) -> Optional[Dict[str, Any]]:
    root = _ensure_disputes_root(ledger)
    return root["cases"].get(case_id)


def list_cases(
    ledger: Dict[str, Any],
    status: Optional[str] = None,
    case_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List cases, optionally filtered by status and/or case_type.
    """
    root = _ensure_disputes_root(ledger)
    cases = list(root["cases"].values())
    if status is not None:
        cases = [c for c in cases if c.get("status") == status]
    if case_type is not None:
        cases = [c for c in cases if c.get("case_type") == case_type]
    return cases


def assign_jurors(
    ledger: Dict[str, Any],
    case_id: str,
    juror_ids: List[str],
) -> Dict[str, Any]:
    """
    Assign jurors to a case.

    Guardrails:
    - Case must exist and not yet be decided.
    - Each juror must pass _has_juror_capability (Tier 3 + opt-in + min score).
    - Adds jurors to the case and moves status → AWAITING_VOTES.
    """
    case = get_case(ledger, case_id)
    if not case:
        raise KeyError(f"Unknown case_id: {case_id}")

    if case["status"] == STATUS_DECIDED:
        raise ValueError("Cannot assign jurors to a decided case")

    now = _timestamp()

    jurors_map = case["jurors"]
    for j in juror_ids:
        if not _has_juror_capability(ledger, j):
            raise ValueError(f"User {j} is not eligible to serve as juror")
        jurors_map.setdefault(j, {
            "assigned_at": now,
            "vote": None,
            "reason": "",
            "voted_at": None,
        })

    case["status"] = STATUS_AWAITING_VOTES
    case["updated_at"] = now
    return case


def apply_juror_vote(
    ledger: Dict[str, Any],
    case_id: str,
    juror_id: str,
    vote: str,
    reason: str = "",
) -> Dict[str, Any]:
    """
    Apply a juror's vote to a dispute case.

    Rules:
    - Case must exist and be in STATUS_AWAITING_VOTES.
    - Juror must be assigned to the case.
    - Vote must be one of VALID_VOTES.
    - If juror changes vote, we adjust aggregates accordingly.
    - If thresholds are hit, status → DECIDED and decision is recorded.
    """
    if vote not in VALID_VOTES:
        raise ValueError(f"Invalid vote: {vote}")

    case = get_case(ledger, case_id)
    if not case:
        raise KeyError(f"Unknown case_id: {case_id}")

    if case["status"] != STATUS_AWAITING_VOTES:
        raise ValueError("Case is not currently accepting votes")

    jurors_map = case["jurors"]
    if juror_id not in jurors_map:
        raise ValueError("Juror is not assigned to this case")

    juror_rec = jurors_map[juror_id]

    agg = case.setdefault("aggregates", {})
    vc = agg.setdefault("vote_counts", {
        VOTE_UPHOLD: 0,
        VOTE_REJECT: 0,
    })

    # Remove previous vote from counts (if any)
    prev_vote = juror_rec.get("vote")
    if prev_vote in VALID_VOTES:
        vc[prev_vote] = max(0, vc.get(prev_vote, 0) - 1)

    # Apply new vote
    juror_rec["vote"] = vote
    juror_rec["reason"] = reason or ""
    juror_rec["voted_at"] = _timestamp()
    vc[vote] = vc.get(vote, 0) + 1

    case["updated_at"] = juror_rec["voted_at"]

    _maybe_finalize_case(ledger, case)
    return case


def _maybe_finalize_case(ledger: Dict[str, Any], case: Dict[str, Any]) -> None:
    """
    Finalize the case once enough jurors have voted.

    Behavior:
    - Let required = case.required_jurors (or number of assigned jurors if missing).
    - Count how many jurors have actually cast a vote.
    - If total_votes < required → do nothing (case stays open).
    - Once total_votes >= required:
        - If approvals >= min_approvals → verdict "upheld".
        - Else → verdict "dismissed".
    """
    if case["status"] != STATUS_AWAITING_VOTES:
        return

    jurors_map = case.get("jurors") or {}
    total_votes = sum(
        1 for j in jurors_map.values()
        if j.get("vote") in VALID_VOTES
    )

    required = int(case.get("required_jurors") or len(jurors_map) or 1)
    if required <= 0:
        required = len(jurors_map) or 1

    # Not enough participation yet → keep case open
    if total_votes < required:
        return

    agg = case.setdefault("aggregates", {})
    vc = agg.setdefault("vote_counts", {
        VOTE_UPHOLD: 0,
        VOTE_REJECT: 0,
    })

    approvals = int(vc.get(VOTE_UPHOLD, 0))
    rejects = int(vc.get(VOTE_REJECT, 0))

    min_approvals = int(case.get("min_approvals") or 1)

    if approvals >= min_approvals:
        _finalize_case(ledger, case, verdict="upheld", approvals=approvals, rejects=rejects)
    else:
        _finalize_case(ledger, case, verdict="dismissed", approvals=approvals, rejects=rejects)


def _finalize_case(
    ledger: Dict[str, Any],
    case: Dict[str, Any],
    verdict: str,
    approvals: int,
    rejects: int,
) -> None:
    """
    Mark the case as decided and update juror reputation.

    MVP policy:

    - Every juror who cast a vote on a decided case gains +1 score.
    - Every assigned juror who failed to vote receives +1 strike.
    """
    case["status"] = STATUS_DECIDED
    case["decision"] = {
        "verdict": verdict,
        "decided_at": _timestamp(),
        "approvals": approvals,
        "rejects": rejects,
    }
    case["updated_at"] = case["decision"]["decided_at"]

    jurors_map = case.get("jurors") or {}
    for juror_id, juror_rec in jurors_map.items():
        profile = _ensure_juror_profile(ledger, juror_id)
        if juror_rec.get("vote"):
            # Participating jurors gain reputation
            profile["score"] = int(profile.get("score", 0)) + 1
        else:
            # No-show jurors accumulate strikes
            profile["strikes"] = int(profile.get("strikes", 0)) + 1


# ---------------------------------------------------------------------------
# Admin / debugging helpers
# ---------------------------------------------------------------------------


def clear_all_disputes(ledger: Dict[str, Any]) -> None:
    """
    Wipe all disputes from the ledger (tests / local dev only).
    """
    if "disputes" in ledger:
        ledger["disputes"]["cases"] = {}


def clear_all_juror_reputation(ledger: Dict[str, Any]) -> None:
    """
    Wipe all juror reputation data (tests / local dev only).
    """
    if "reputation" in ledger and "jurors" in ledger["reputation"]:
        ledger["reputation"]["jurors"] = {}
