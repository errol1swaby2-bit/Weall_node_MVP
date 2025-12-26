"""
weall_node/core/poh_gate.py

Tier gating for WeAll (current model)

Tier 0: view-only
Tier 1: like + comment
Tier 2: vote + join groups + post content
Tier 3: everything else

Notes:
- Tier is a capability gate (what actions are allowed).
- Reputation remains the primary trust / forgiveness system.
"""

from __future__ import annotations

from fastapi import HTTPException, status


def require_poh(tier: int | None, min_tier: int, *, action: str = "action") -> None:
    """
    Enforce that the caller has at least `min_tier`.

    Parameters
    ----------
    tier:
        Current user's tier (0..3). None treated as 0.
    min_tier:
        Minimum tier required.
    action:
        Human-readable action name for error messages.
    """
    t = int(tier or 0)
    if t < int(min_tier):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tier {min_tier}+ required for {action}. Your tier: {t}.",
        )


# Convenience wrappers (use these in endpoints for clarity)

def require_view(tier: int | None) -> None:
    require_poh(tier, 0, action="view")


def require_like_comment(tier: int | None) -> None:
    require_poh(tier, 1, action="like/comment")


def require_vote_join_post(tier: int | None) -> None:
    require_poh(tier, 2, action="vote/join/post")


def require_everything_else(tier: int | None) -> None:
    require_poh(tier, 3, action="tier-3 actions")
