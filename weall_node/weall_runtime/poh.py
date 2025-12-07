# weall_node/weall_runtime/poh.py
from __future__ import annotations

"""
Proof-of-Humanity (PoH) runtime for WeAll.

This module manages PoH records and their enforcement status.

Data model
----------
executor.ledger["poh"] = {
    "records": {
        user_id: {
            "user_id": str,
            "poh_id": str,            # canonical identity id (often same as user_id)
            "tier": int,              # 0 (none), 1, 2, 3
            "status": str,            # "ok" | "downgraded" | "suspended" | "banned"
            "created_at": float,
            "updated_at": float,
            "revoked": bool,          # derived legacy flag (status in suspended/banned)
            "keys": {
                "current_pk": str | None,
                "historical": [
                    {"old_pk": str, "new_pk": str, "at": float, "case_id": str | None}
                ],
            },
        },
        ...
    },
    "enforcements": [
        {
            "poh_id": str,
            "status": str,
            "reason": str,
            "case_id": str | None,
            "at": float,
        },
        ...
    ],
}
"""

import time
from typing import Dict, Optional

from ..weall_executor import executor


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_poh_ledger() -> Dict[str, dict]:
    ledger = executor.ledger
    poh_ns = ledger.setdefault("poh", {})
    poh_ns.setdefault("records", {})
    poh_ns.setdefault("enforcements", [])
    return poh_ns  # type: ignore[return-value]


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_poh_record(user_id: str) -> Optional[dict]:
    """
    Return the PoH record for a given user_id (or None if missing).
    """
    poh_ns = _ensure_poh_ledger()
    return poh_ns["records"].get(user_id)


def ensure_poh_record(user_id: str) -> dict:
    """
    Ensure a PoH record exists for this user_id and return it.

    Default record:
    - tier = 0
    - status = "ok"
    - revoked = False
    """
    poh_ns = _ensure_poh_ledger()
    rec = poh_ns["records"].get(user_id)
    now = _now()
    if rec is None:
        rec = {
            "user_id": user_id,
            "poh_id": user_id,
            "tier": 0,
            "status": "ok",
            "created_at": now,
            "updated_at": now,
            "revoked": False,
            "keys": {
                "current_pk": None,
                "historical": [],
            },
        }
        poh_ns["records"][user_id] = rec
        _maybe_save_state()
    return rec


def set_poh_tier(user_id: str, tier: int) -> dict:
    """
    Set the PoH tier for a given user.

    This does NOT change status. Tiers are normally:
    - 0: no PoH
    - 1: basic (e.g. email + minimal checks)
    - 2: stronger (async liveness, etc.)
    - 3: full PoH (juror-eligible, validator-eligible, etc.)
    """
    if tier < 0:
        raise ValueError("tier must be >= 0")
    rec = ensure_poh_record(user_id)
    rec["tier"] = int(tier)
    rec["updated_at"] = _now()
    _maybe_save_state()
    return rec


def set_poh_status(
    user_id: str,
    status: str,
    reason: str,
    case_id: Optional[str] = None,
) -> dict:
    """
    Set enforcement status for a PoH identity.

    Allowed statuses:
    - "ok"          : normal
    - "downgraded"  : PoH tier reduced (e.g. 3 -> 1)
    - "suspended"   : temporarily not allowed to act
    - "banned"      : permanently banned (may trigger economic actions)

    This function updates:
    - record["status"]
    - record["revoked"] (derived: True if status in {"suspended", "banned"})
    - enforcement log in executor.ledger["poh"]["enforcements"]
    """
    allowed = {"ok", "downgraded", "suspended", "banned"}
    if status not in allowed:
        raise ValueError(f"status must be one of {sorted(allowed)}")

    poh_ns = _ensure_poh_ledger()
    rec = ensure_poh_record(user_id)
    rec["status"] = status
    rec["revoked"] = status in {"suspended", "banned"}
    rec["updated_at"] = _now()

    poh_ns["enforcements"].append(
        {
            "poh_id": rec["poh_id"],
            "status": status,
            "reason": reason,
            "case_id": case_id,
            "at": _now(),
        }
    )
    _maybe_save_state()
    return rec


def bind_account_key(user_id: str, account_pk_hex: str) -> dict:
    """
    Bind an account public key to this PoH identity.

    This sets "keys.current_pk" if not already set. It does not touch
    historical records (it is assumed to be an initial bind).
    """
    rec = ensure_poh_record(user_id)
    keys = rec.setdefault("keys", {})
    if keys.get("current_pk") is None:
        keys["current_pk"] = account_pk_hex
        rec["updated_at"] = _now()
        _maybe_save_state()
    return rec


def rebind_account_key(
    user_id: str,
    old_pk_hex: Optional[str],
    new_pk_hex: str,
    *,
    case_id: Optional[str] = None,
) -> dict:
    """
    Rebind an account public key for this PoH identity.

    This is used by the recovery flow once a juror-backed recovery
    decision has been finalized.

    - If old_pk_hex is provided and doesn't match the current_pk, the
      operation still proceeds but records the mismatch in history.
    - The old current_pk (if any) is appended to the historical list.
    """
    rec = ensure_poh_record(user_id)
    keys = rec.setdefault("keys", {})
    current = keys.get("current_pk")
    history = keys.setdefault("historical", [])

    history.append(
        {
            "old_pk": current,
            "new_pk": new_pk_hex,
            "at": _now(),
            "case_id": case_id,
            "claimed_old_pk": old_pk_hex,
        }
    )
    keys["current_pk"] = new_pk_hex
    rec["updated_at"] = _now()
    _maybe_save_state()
    return rec


def is_banned(user_id: str) -> bool:
    rec = get_poh_record(user_id)
    if not rec:
        return False
    return rec.get("status") == "banned"


def is_suspended(user_id: str) -> bool:
    rec = get_poh_record(user_id)
    if not rec:
        return False
    return rec.get("status") == "suspended"


def _maybe_save_state() -> None:
    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()
