from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import HTTPException

from weall_node.weall_executor import executor


def _ledger() -> Dict[str, Any]:
    """
    Return the canonical executor ledger dict.
    Falls back to an empty dict if not present (defensive for tests).
    """
    ledger = getattr(executor, "ledger", None)
    if ledger is None:
        ledger = {}
        executor.ledger = ledger  # type: ignore[attr-defined]
    return ledger


def _poh_bucket() -> Dict[str, Any]:
    """
    Ensure and return the PoH registry within the ledger.

    Structure:
    ledger["poh"] = {
        "<user_id>": {
            "tier": int,
            "revoked": bool,
            "source": str,
            "updated_at": int,
            "revocation_reason": Optional[str],
        },
        ...
    }
    """
    ledger = _ledger()
    poh = ledger.get("poh")
    if not isinstance(poh, dict):
        poh = {}
        ledger["poh"] = poh
    return poh


def get_poh_record(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Read-only helper for PoH info for a given user_id.
    """
    if not user_id:
        return None
    poh = _poh_bucket()
    return poh.get(user_id)


def set_poh_tier(user_id: str, tier: int, source: str = "poh_flow") -> Dict[str, Any]:
    """
    Idempotently set/update a user's PoH tier in the ledger.
    Does NOT persist to disk by itself; caller should invoke executor.save_state().
    """
    if not user_id:
        raise ValueError("user_id is required for set_poh_tier")

    if tier < 0:
        tier = 0

    poh = _poh_bucket()
    rec = poh.get(user_id, {})
    rec.update(
        {
            "tier": int(tier),
            "revoked": False,
            "source": source,
            "updated_at": int(time.time()),
            "revocation_reason": rec.get("revocation_reason"),
        }
    )
    poh[user_id] = rec
    return rec


def revoke_poh(user_id: str, reason: str = "revoked") -> Optional[Dict[str, Any]]:
    """
    Mark a PoH record as revoked.
    Does NOT persist to disk by itself; caller should invoke executor.save_state().
    """
    if not user_id:
        return None

    poh = _poh_bucket()
    rec = poh.get(user_id)
    if not rec:
        return None

    rec.update(
        {
            "revoked": True,
            "revocation_reason": reason,
            "updated_at": int(time.time()),
        }
    )
    poh[user_id] = rec
    return rec


def require_tier(user_id: str, min_tier: int) -> None:
    """
    Enforce that a user has at least `min_tier` and is not revoked.

    Usage (inside an endpoint):

        from weall_node.security.permissions import require_tier

        @router.post("/validators/register")
        def register_validator(user=Depends(auth_session)):
            require_tier(user.user_id, 3)
            ...

    Raises HTTPException(403) on failure.
    """
    if min_tier <= 0:
        return

    rec = get_poh_record(user_id)
    if not rec:
        raise HTTPException(status_code=403, detail=f"PoH Tier {min_tier}+ required")

    if rec.get("revoked"):
        raise HTTPException(status_code=403, detail="PoH status revoked")

    tier = int(rec.get("tier", 0))
    if tier < min_tier:
        raise HTTPException(status_code=403, detail=f"PoH Tier {min_tier}+ required")
