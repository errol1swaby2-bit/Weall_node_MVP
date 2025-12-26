from __future__ import annotations

"""
weall_node/security/permissions.py
---------------------------------

Shared permission helpers for API routes.

This module intentionally avoids "confiscation" patterns.

Implemented policy:
- reputation score is a sliding scale [-1, 1]
- at rep <= -1.0, the account is auto-banned from all network actions
- HOWEVER: wallet transfer / withdrawal endpoints should NOT call the
  auto-ban check if you want an "exit lane" so users can move funds out.

This file provides:
- rep conversion utilities (float <-> int scaled)
- ensure_not_autobanned_by_reputation()
- rep threshold helper ensure_min_reputation()
"""

from dataclasses import dataclass
from typing import Any, Optional


REP_SCALE: int = 10_000
REP_MIN_I: int = -REP_SCALE
REP_MAX_I: int = REP_SCALE


def rep_float_to_int(rep: float) -> int:
    """
    Deterministic conversion:
    - store comparisons in integer space to avoid float edge cases.
    """
    if rep <= -1.0:
        return REP_MIN_I
    if rep >= 1.0:
        return REP_MAX_I
    return int(round(rep * REP_SCALE))


def rep_int_to_float(rep_i: int) -> float:
    if rep_i <= REP_MIN_I:
        return -1.0
    if rep_i >= REP_MAX_I:
        return 1.0
    return float(rep_i) / float(REP_SCALE)


@dataclass(frozen=True)
class PermissionContext:
    """
    Optional context object for debugging / audit logs.
    """

    action: str
    reason: str
    detail: Optional[str] = None


class PermissionError(Exception):
    """
    Raised when a permission check fails.
    """

    def __init__(self, message: str, ctx: Optional[PermissionContext] = None):
        super().__init__(message)
        self.ctx = ctx


def get_reputation_value(actor: Any) -> float:
    """
    Reads reputation from a generic actor structure.

    Supported patterns:
    - actor.reputation (float)
    - actor["reputation"] (float)
    - actor.rep (float)
    - actor["rep"] (float)
    """
    if actor is None:
        return 0.0

    for key in ("reputation", "rep"):
        if hasattr(actor, key):
            try:
                v = float(getattr(actor, key))
                return v
            except Exception:
                pass
        if isinstance(actor, dict) and key in actor:
            try:
                v = float(actor[key])
                return v
            except Exception:
                pass
    return 0.0


def ensure_not_autobanned_by_reputation(
    actor: Any,
    *,
    action: str = "unknown",
) -> None:
    """
    Enforces auto-ban rule: rep <= -1.0 -> deny.

    IMPORTANT:
    Do not call this from wallet-transfer endpoints if you want
    "ban = no access, but can move funds out".
    """
    rep = get_reputation_value(actor)
    rep_i = rep_float_to_int(rep)
    if rep_i <= REP_MIN_I:
        raise PermissionError(
            "Account is banned by network (reputation <= -1.0).",
            PermissionContext(action=action, reason="autoban_reputation", detail=f"rep={rep} rep_i={rep_i}"),
        )


def ensure_min_reputation(
    actor: Any,
    min_rep: float,
    *,
    action: str = "unknown",
) -> None:
    """
    Requires rep >= min_rep.
    """
    rep = get_reputation_value(actor)
    rep_i = rep_float_to_int(rep)
    min_rep_i = rep_float_to_int(min_rep)

    if rep_i < min_rep_i:
        raise PermissionError(
            f"Reputation too low for action '{action}'. Required >= {min_rep:.2f}",
            PermissionContext(action=action, reason="min_reputation", detail=f"rep={rep} rep_i={rep_i} min_rep={min_rep}"),
        )
