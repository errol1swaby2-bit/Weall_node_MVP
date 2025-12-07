# weall_node/security/permissions.py
from __future__ import annotations

"""
Permission helpers for WeAll.

This module centralizes the logic for:

- PoH-based access control
    * tiers (0/1/2/3)
    * status flags: "ok" | "downgraded" | "suspended" | "banned"

- Reputation-based access control
    * minimum reputation thresholds for roles (validator, juror, operator, etc.)

By routing all checks through here, we keep the rest of the API modules
simple and ensure consistent semantics across the node.
"""

from typing import Optional

from fastapi import HTTPException, status

from ..weall_executor import executor
from ..weall_runtime import poh as poh_rt


# ---------------------------------------------------------------------------
# Helpers to access runtime components
# ---------------------------------------------------------------------------


def _get_reputation_runtime():
    rep = getattr(executor, "reputation", None)
    if rep is None:
        return None
    return rep


# ---------------------------------------------------------------------------
# PoH-based checks
# ---------------------------------------------------------------------------


def get_poh_record(user_id: str) -> Optional[dict]:
    """
    Convenience helper to fetch a PoH record from the runtime.
    """
    return poh_rt.get_poh_record(user_id)


def ensure_not_banned(user_id: str, detail: str = "Account is banned.") -> None:
    """
    Raise HTTP 403 if the user is banned.

    This is the lowest-level ban check. Most callers will use
    ensure_poh_tier which already checks for bans/suspensions.
    """
    rec = get_poh_record(user_id)
    if not rec:
        return
    status_str = rec.get("status")
    if status_str == "banned":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def ensure_poh_tier(
    user_id: str,
    min_tier: int,
    detail: Optional[str] = None,
) -> None:
    """
    Ensure a user has at least the given PoH tier and is not banned.

    Raises HTTP 403 if:

    - user has no PoH record or tier < min_tier
    - user is banned
    - user is suspended (for now we treat suspension as a hard block)

    Parameters
    ----------
    user_id : str
        Identity / handle.
    min_tier : int
        Required PoH tier.
    detail : Optional[str]
        Optional additional detail to include in error messages.
    """
    rec = get_poh_record(user_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
            or f"User {user_id!r} has no PoH record and does not meet tier {min_tier}.",
        )

    tier = int(rec.get("tier", 0))
    status_str = rec.get("status", "ok")
    revoked = bool(rec.get("revoked", False))

    if status_str == "banned":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or "Account is banned from participating.",
        )

    if status_str == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or "Account is temporarily suspended.",
        )

    if revoked:
        # Legacy safety net: if revoked is still set, treat as blocked.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or "Account PoH record is revoked.",
        )

    if tier < min_tier:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
            or f"PoH tier {tier} is below the required minimum {min_tier}.",
        )


# ---------------------------------------------------------------------------
# Reputation-based checks
# ---------------------------------------------------------------------------


def get_reputation(user_id: str) -> float:
    """
    Return the current reputation score for a user.

    If the reputation runtime is not available, returns 0.0 as a safe
    default, effectively disabling reputation gates (but logging should
    highlight that situation).
    """
    rep_rt = _get_reputation_runtime()
    if rep_rt is None:
        # In environments without a reputation runtime, we treat users as
        # neutral reputation. You may wish to log this situation elsewhere.
        return 0.0
    get_score = getattr(rep_rt, "get_score", None)
    if not callable(get_score):
        return 0.0
    try:
        return float(get_score(user_id))
    except Exception:
        return 0.0


def ensure_min_reputation(
    user_id: str,
    min_rep: float,
    action_name: str = "this action",
) -> None:
    """
    Ensure a user has at least the given reputation score.

    Raises HTTP 403 if the user's reputation is below the threshold.
    """
    score = get_reputation(user_id)
    if score < min_rep:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Reputation {score:.3f} is below the required minimum "
                f"{min_rep:.3f} for {action_name}."
            ),
        )


# ---------------------------------------------------------------------------
# Composite helpers for common roles
# ---------------------------------------------------------------------------

# You can tune these thresholds over time or move them into a YAML config.


VALIDATOR_MIN_TIER = 3
VALIDATOR_MIN_REP = 0.0

JUROR_MIN_TIER = 3
JUROR_MIN_REP = 0.0

OPERATOR_MIN_TIER = 2
OPERATOR_MIN_REP = 0.0


def ensure_validator_eligibility(user_id: str) -> None:
    """
    Ensure a user is eligible to act as a validator.

    Default policy:
    - PoH tier >= 3
    - reputation >= VALIDATOR_MIN_REP
    """
    ensure_poh_tier(user_id, VALIDATOR_MIN_TIER, detail="Validator requires Tier-3 PoH.")
    ensure_min_reputation(
        user_id, VALIDATOR_MIN_REP, action_name="validator participation"
    )


def ensure_juror_eligibility(user_id: str) -> None:
    """
    Ensure a user is eligible to act as a juror.

    Default policy:
    - PoH tier >= 3
    - reputation >= JUROR_MIN_REP
    """
    ensure_poh_tier(user_id, JUROR_MIN_TIER, detail="Juror requires Tier-3 PoH.")
    ensure_min_reputation(user_id, JUROR_MIN_REP, action_name="juror participation")


def ensure_operator_eligibility(user_id: str) -> None:
    """
    Ensure a user is eligible to act as a node/operator.

    Default policy:
    - PoH tier >= 2
    - reputation >= OPERATOR_MIN_REP
    """
    ensure_poh_tier(
        user_id,
        OPERATOR_MIN_TIER,
        detail="Operator requires at least Tier-2 PoH.",
    )
    ensure_min_reputation(user_id, OPERATOR_MIN_REP, action_name="operator participation")
