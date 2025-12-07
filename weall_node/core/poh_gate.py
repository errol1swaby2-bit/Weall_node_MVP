"""
weall_node/core/poh_gate.py
---------------------------
Backward-compatible PoH gating + rejection logging helpers.

This module exists primarily so that API modules like `api/sync.py`
can import a stable interface:

    from ..core.poh_gate import (
        MIN_TIER,
        get_min_tier,
        poh_min_tier_config,
        ensure_min_tier,
        require_poh,
        get_poh_tier,
        log_block_rejection,
        get_rejection_stats,
    )

Design:
- No dependency on executor or global settings (to avoid cycles).
- MIN_TIER is a simple constant for now; can be wired to config later.
- Rejection stats are kept in-process, in-memory only. They are meant
  for diagnostics, not canonical protocol state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger("weall.poh_gate")

# -------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------

#: Default minimum PoH tier for "sensitive" actions.
#: Routes are free to require higher tiers explicitly.
MIN_TIER: int = 1

# In-memory rejection stats for diagnostics
_REJECTION_TOTAL: int = 0
_REJECTION_BY_REASON: Dict[str, int] = {}


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def _config_min_tier() -> int:
    """
    Placeholder for config-based minimum tier.

    For now we simply return the constant MIN_TIER, but this is kept as
    a separate function so it can be extended later to read from a
    Settings object or environment variable without changing callers.
    """
    return MIN_TIER


# -------------------------------------------------------------------
# Public API — tier helpers
# -------------------------------------------------------------------

def get_min_tier() -> int:
    """
    Return the effective minimum PoH tier.

    Currently just returns MIN_TIER. In future this may read from
    configuration.
    """
    return _config_min_tier()


def poh_min_tier_config() -> int:
    """
    Backwards-compatible alias used by some older modules.

    Equivalent to get_min_tier().
    """
    return get_min_tier()


def ensure_min_tier(current_tier: int | None, min_tier: int | None = None) -> None:
    """
    Ensure that a given user tier meets or exceeds the required tier.

    Args:
        current_tier: The caller's current PoH tier (or None if unknown).
        min_tier:     The required tier. If None, uses get_min_tier().

    Raises:
        HTTPException(401) if the tier is unknown.
        HTTPException(403) if the tier is below the required threshold.
    """
    if current_tier is None:
        raise HTTPException(status_code=401, detail="PoH tier is unknown")

    required = min_tier if min_tier is not None else get_min_tier()
    if current_tier < required:
        raise HTTPException(
            status_code=403,
            detail=f"Requires PoH tier {required} or higher",
        )


def require_poh(current_tier: int | None, min_tier: int | None = None) -> None:
    """
    Backwards-compatible name used by some API modules.

    Simply forwards to ensure_min_tier().
    """
    ensure_min_tier(current_tier=current_tier, min_tier=min_tier)


def get_poh_tier(record: Optional[Dict[str, Any]]) -> Optional[int]:
    """
    Legacy helper used by some API modules.

    Expects a user / PoH record dict with a 'tier' key.
    Returns:
        - int tier value if present and parseable
        - 0 if 'tier' is missing
        - None if record itself is None

    Newer code should prefer explicit PoH runtime helpers; this exists
    so older imports keep working.
    """
    if record is None:
        return None
    try:
        return int(record.get("tier", 0))
    except Exception:
        return 0


# -------------------------------------------------------------------
# Public API — rejection logging
# -------------------------------------------------------------------

def log_block_rejection(reason: str, context: Optional[Dict[str, Any]] = None) -> None:
    """
    Legacy logging hook for rejected blocks / actions.

    Older code paths call this when a block proposal or sync action is
    rejected for PoH-related or safety reasons. We keep it lightweight
    and side-effect free: it only logs to the Python logger and updates
    in-memory counters.

    Args:
        reason:  Short human-readable reason string.
        context: Optional dict with extra fields (e.g., node_id, height).
    """
    global _REJECTION_TOTAL, _REJECTION_BY_REASON

    if context is None:
        context = {}

    try:
        logger.warning("Block/action rejected: %s | context=%r", reason, context)
    except Exception:
        # Never let logging crash the node.
        pass

    # Update in-memory counters (best-effort)
    try:
        _REJECTION_TOTAL += 1
        _REJECTION_BY_REASON[reason] = _REJECTION_BY_REASON.get(reason, 0) + 1
    except Exception:
        # Also must not crash on stats update.
        pass


def get_rejection_stats() -> Dict[str, Any]:
    """
    Return a snapshot of in-memory rejection statistics.

    Structure:
        {
          "total": int,
          "by_reason": {reason: count, ...}
        }

    This is for diagnostics only; it is NOT persisted or consensus-
    relevant state.
    """
    # Shallow copies to avoid outside mutation.
    return {
        "total": int(_REJECTION_TOTAL),
        "by_reason": dict(_REJECTION_BY_REASON),
    }
