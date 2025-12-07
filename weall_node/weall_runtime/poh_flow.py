from __future__ import annotations

"""
weall_node/weall_runtime/poh_flow.py
------------------------------------

MVP PoH upgrade-request pipeline.

This keeps track of PoH tier-upgrade requests in the executor ledger:

    executor.ledger["poh"]["upgrade_requests"] = {
        request_id: {
            "id": str,
            "user_id": str,
            "current_tier": int,
            "target_tier": int,
            "status": str,  # "pending" | "approved" | "rejected" | "cancelled" | "noop"
            "video_cid": Optional[str],
            "note": str,
            "created_at": float,
            "updated_at": float,
            "decided_at": Optional[float],
            "decision": Optional[str],
            "decided_by": Optional[str],
        },
        ...
    }

The actual juror / liveness / dispute flows can build on top of this
simple request log.
"""

from typing import Dict, Any, List, Optional
import time
import secrets

from weall_node.weall_executor import executor
from .poh import get_poh_record, set_poh_tier


def _now() -> float:
    return time.time()


def _ns() -> Dict[str, Any]:
    """
    Return the PoH namespace in the executor ledger, ensuring the
    expected sub-structures exist.
    """
    state = executor.ledger.setdefault("poh", {})
    state.setdefault("records", {})
    state.setdefault("history", [])
    state.setdefault("enforcements", [])
    state.setdefault("upgrade_requests", {})
    return state


def _requests() -> Dict[str, dict]:
    return _ns().setdefault("upgrade_requests", {})


def _maybe_save_state() -> None:
    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()


def submit_upgrade_request(
    user_id: str,
    target_tier: int,
    *,
    video_cid: Optional[str] = None,
    note: str = "",
    auto_approve: bool = False,
) -> dict:
    """
    Record a PoH tier-upgrade request.

    - If the user already has >= target_tier, a synthetic "noop"
      record is returned instead of creating a new pending request.
    - If there is an existing pending request for the same user and
      target_tier, that request is returned instead.
    """
    reqs = _requests()

    # Try to dedupe existing pending request
    for r in reqs.values():
        if (
            r.get("user_id") == user_id
            and int(r.get("target_tier", 0)) == int(target_tier)
            and r.get("status") == "pending"
        ):
            return r

    rec = get_poh_record(user_id)
    current_tier = int(rec.get("tier", 0)) if rec else 0
    target_tier = int(target_tier)

    # Already at or above target tier → no-op record
    if target_tier <= current_tier:
        now = _now()
        noop = {
            "id": None,
            "user_id": user_id,
            "current_tier": current_tier,
            "target_tier": target_tier,
            "status": "noop",
            "video_cid": video_cid,
            "note": note or "",
            "created_at": now,
            "updated_at": now,
            "decided_at": now,
            "decision": "already_at_or_above_tier",
            "decided_by": None,
        }
        return noop

    now = _now()
    req_id = secrets.token_hex(8)
    req = {
        "id": req_id,
        "user_id": user_id,
        "current_tier": current_tier,
        "target_tier": target_tier,
        "status": "pending",
        "video_cid": video_cid,
        "note": note or "",
        "created_at": now,
        "updated_at": now,
        "decided_at": None,
        "decision": None,
        "decided_by": None,
    }
    reqs[req_id] = req
    _maybe_save_state()

    if auto_approve:
        return approve_request(req_id, decided_by="auto-dev")

    return req


def list_requests_for_user(user_id: str) -> List[dict]:
    """
    Return all upgrade requests for a given user_id.
    """
    reqs = _requests()
    return [r for r in reqs.values() if r.get("user_id") == user_id]


def list_all_requests() -> List[dict]:
    """
    Return all upgrade requests (dev / operator helper).
    """
    return list(_requests().values())


def get_request(request_id: str) -> Optional[dict]:
    return _requests().get(request_id)


def approve_request(request_id: str, decided_by: Optional[str] = None) -> dict:
    """
    Mark an upgrade request as approved and bump the PoH tier.
    """
    reqs = _requests()
    req = reqs.get(request_id)
    if not req:
        raise KeyError("upgrade_request_not_found")

    if req.get("status") in {"approved", "rejected", "cancelled"}:
        return req

    target_tier = int(req.get("target_tier", 0))
    set_poh_tier(req["user_id"], target_tier)

    now = _now()
    req["status"] = "approved"
    req["decided_at"] = now
    req["updated_at"] = now
    req["decision"] = f"upgraded_to_{target_tier}"
    req["decided_by"] = decided_by or "system"

    _maybe_save_state()
    return req


def reject_request(
    request_id: str,
    decided_by: Optional[str] = None,
    reason: str = "",
) -> dict:
    """
    Mark an upgrade request as rejected.
    """
    reqs = _requests()
    req = reqs.get(request_id)
    if not req:
        raise KeyError("upgrade_request_not_found")

    if req.get("status") in {"approved", "rejected", "cancelled"}:
        return req

    now = _now()
    req["status"] = "rejected"
    req["decided_at"] = now
    req["updated_at"] = now
    req["decision"] = reason or "rejected"
    req["decided_by"] = decided_by or "system"

    _maybe_save_state()
    return req
