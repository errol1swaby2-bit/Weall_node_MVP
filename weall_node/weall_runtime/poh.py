"""
weall_node/weall_runtime/poh.py
----------------------------------
Proof-of-Humanity runtime + ledger helpers.

This module centralises how PoH state is persisted in the unified ledger.

Spec alignment
--------------
- Section 3: Identity & PoH tiers (Tier1/2/3)
- Section 3.5: Revocation & recovery (ledger-backed flags)
- Section 5.3 / 6.1: PoH-gated consensus (other modules consume ledger["poh"])
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List

try:
    # The executor is the single source of truth for the ledger.
    from weall_node.weall_executor import executor  # type: ignore
except Exception:  # pragma: no cover - makes tests/imports safer
    executor = None  # type: ignore


# ---------------------------------------------------------------------------
# Low-level ledger helpers
# ---------------------------------------------------------------------------

def _ledger() -> Dict[str, Any]:
    """
    Return the canonical executor.ledger dict, creating an empty one if needed.

    This keeps PoH state in the same JSON that backs weall_state.json.
    """
    global executor
    led: Any = getattr(executor, "ledger", None)
    if not isinstance(led, dict):
        led = {}
        try:
            # type: ignore[assignment]
            executor.ledger = led
        except Exception:
            pass
    return led  # type: ignore[return-value]


def _poh_bucket() -> Dict[str, Dict[str, Any]]:
    """
    Return the ledger["poh"] mapping: user_id -> PoH record.
    Creates it on first use and normalises unexpected types.
    """
    led = _ledger()
    bucket = led.get("poh")
    if not isinstance(bucket, dict):
        bucket = {}
        led["poh"] = bucket
    return bucket  # type: ignore[return-value]


def _t2_queue_bucket() -> Dict[str, Dict[str, Any]]:
    """
    Return the ledger["poh_t2_queue"] mapping: account_id -> Tier-2 application.
    This replaces the old in-memory queue so state survives restarts.
    """
    led = _ledger()
    bucket = led.get("poh_t2_queue")
    if not isinstance(bucket, dict):
        bucket = {}
        led["poh_t2_queue"] = bucket
    return bucket  # type: ignore[return-value]


def _t2_config_bucket() -> Dict[str, Any]:
    """
    Return the Tier-2 config stored under ledger["poh_t2_config"].
    """
    led = _ledger()
    cfg = led.get("poh_t2_config")
    if not isinstance(cfg, dict):
        cfg = {
            "required_yes": 3,
            "max_pending": 128,
        }
        led["poh_t2_config"] = cfg
    # normalise keys
    if "required_yes" not in cfg:
        cfg["required_yes"] = 3
    if "max_pending" not in cfg:
        cfg["max_pending"] = 128
    return cfg  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public helpers used by the API layer & other modules
# ---------------------------------------------------------------------------

def get_poh_record(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up a user's PoH record from the ledger.

    Shape of the record (per spec & existing state):
        {
            "tier": int,
            "revoked": bool,
            "source": str,
            "updated_at": int (unix ts),
            "revocation_reason": Optional[str],
        }
    """
    if not user_id:
        return None
    bucket = _poh_bucket()
    rec = bucket.get(str(user_id))
    if rec is None:
        return None
    # defensive normalisation
    try:
        rec["tier"] = int(rec.get("tier", 0))
    except Exception:
        rec["tier"] = 0
    rec["revoked"] = bool(rec.get("revoked", False))
    rec.setdefault("source", "unknown")
    rec.setdefault("updated_at", int(time.time()))
    rec.setdefault("revocation_reason", None)
    return rec


def set_poh_tier(
    user_id: str,
    tier: int,
    source: str = "manual",
    revoked: bool = False,
    revocation_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persist a user's PoH tier in ledger["poh"] and mirror useful fields into
    ledger["accounts"][user_id] for convenience.

    This is the single place that should mutate PoH tier state.
    """
    if not user_id:
        raise ValueError("user_id is required")

    bucket = _poh_bucket()
    now = int(time.time())
    rec = bucket.get(user_id) or {
        "tier": 0,
        "revoked": False,
        "source": "unknown",
        "updated_at": now,
        "revocation_reason": None,
    }

    rec.update(
        {
            "tier": int(tier),
            "revoked": bool(revoked),
            "source": str(source or "manual"),
            "updated_at": now,
            "revocation_reason": revocation_reason,
        }
    )
    bucket[user_id] = rec

    # Keep a minimal mirror on accounts for other modules.
    try:
        led = _ledger()
        accounts = led.setdefault("accounts", {})
        acct = accounts.setdefault(user_id, {})
        acct["poh_tier"] = rec["tier"]
        acct["poh_revoked"] = rec["revoked"]
    except Exception:
        # Never let bookkeeping failures crash the node.
        pass

    # Best-effort persistence
    try:
        save_state = getattr(executor, "save_state", None)
        if callable(save_state):
            save_state()
    except Exception:
        pass

    return rec


def set_poh_revoked(
    user_id: str,
    revoked: bool = True,
    reason: Optional[str] = None,
    source: str = "revocation",
) -> Dict[str, Any]:
    """
    Convenience helper to revoke/unrevoke a user's PoH status.
    """
    rec = get_poh_record(user_id) or {
        "tier": 0,
        "revoked": False,
        "source": "unknown",
        "updated_at": int(time.time()),
        "revocation_reason": None,
    }
    return set_poh_tier(
        user_id=user_id,
        tier=int(rec.get("tier", 0)),
        source=source,
        revoked=revoked,
        revocation_reason=reason,
    )


def get_t2_config() -> Dict[str, Any]:
    """
    Return Tier-2 configuration (required_yes, max_pending).
    """
    return dict(_t2_config_bucket())


def update_t2_config(required_yes: Optional[int] = None, max_pending: Optional[int] = None) -> Dict[str, Any]:
    """
    Update Tier-2 configuration in the ledger.
    """
    cfg = _t2_config_bucket()
    if required_yes is not None and required_yes > 0:
        cfg["required_yes"] = int(required_yes)
    if max_pending is not None and max_pending > 0:
        cfg["max_pending"] = int(max_pending)

    # Best-effort persistence
    try:
        save_state = getattr(executor, "save_state", None)
        if callable(save_state):
            save_state()
    except Exception:
        pass

    return dict(cfg)


def get_t2_queue() -> Dict[str, Dict[str, Any]]:
    """
    Expose the Tier-2 queue for read-only operations.
    Callers should treat the returned dict as read-only or
    copy it before mutating.
    """
    bucket = _t2_queue_bucket()
    # Return a shallow copy to discourage accidental in-place changes.
    return {k: dict(v) for k, v in bucket.items()}


def upsert_t2_application(
    account_id: str,
    videos: Optional[List[str]] = None,
    title: str = "",
    desc: str = "",
) -> Dict[str, Any]:
    """
    Create or update a Tier-2 application entry in ledger["poh_t2_queue"].

    Does not change the applicant's PoH tier; that is handled by juror votes.
    """
    if not account_id:
        raise ValueError("account_id is required")

    bucket = _t2_queue_bucket()
    now = int(time.time())
    app = bucket.get(account_id) or {
        "account_id": account_id,
        "videos": [],
        "title": "",
        "desc": "",
        "status": "pending",
        "submitted_at": now,
        "updated_at": now,
        "yes": 0,
        "no": 0,
        "votes": [],  # list of {juror_id, approve, time}
    }

    if videos is not None:
        app["videos"] = list(videos)
    if title:
        app["title"] = title
    if desc:
        app["desc"] = desc

    app["status"] = app.get("status", "pending")
    app["updated_at"] = now
    bucket[account_id] = app

    try:
        save_state = getattr(executor, "save_state", None)
        if callable(save_state):
            save_state()
    except Exception:
        pass

    return app


def register_t2_vote(
    candidate_id: str,
    juror_id: str,
    approve: bool,
) -> Dict[str, Any]:
    """
    Register a juror's vote on a Tier-2 application.

    When the application reaches the configured required_yes threshold,
    this helper will automatically:
        - mark status = "approved"
        - set PoH tier to 2 for the candidate (if not already >=2)
    """
    if not candidate_id:
        raise ValueError("candidate_id is required")
    if not juror_id:
        raise ValueError("juror_id is required")

    bucket = _t2_queue_bucket()
    app = bucket.get(candidate_id)
    if not app:
        raise KeyError(f"No Tier-2 application found for {candidate_id!r}")

    # Prevent duplicate votes from the same juror.
    votes: List[Dict[str, Any]] = app.setdefault("votes", [])
    for v in votes:
        if v.get("juror_id") == juror_id:
            # Idempotent: update existing vote in-place.
            v["approve"] = bool(approve)
            v["time"] = int(time.time())
            break
    else:
        votes.append(
            {
                "juror_id": juror_id,
                "approve": bool(approve),
                "time": int(time.time()),
            }
        )

    # Recompute tallies.
    yes = sum(1 for v in votes if v.get("approve") is True)
    no = sum(1 for v in votes if v.get("approve") is False)
    app["yes"] = int(yes)
    app["no"] = int(no)

    cfg = _t2_config_bucket()
    required_yes = int(cfg.get("required_yes", 3))
    if app.get("status") == "pending" and yes >= required_yes:
        # Auto-approve and upgrade to Tier 2.
        app["status"] = "approved"
        set_poh_tier(
            candidate_id,
            tier=max(2, int((get_poh_record(candidate_id) or {}).get("tier", 0))),
            source="tier2_jurors",
        )

    bucket[candidate_id] = app

    try:
        save_state = getattr(executor, "save_state", None)
        if callable(save_state):
            save_state()
    except Exception:
        pass

    return app


# ---------------------------------------------------------------------------
# Optional higher-level runtime wrapper
# ---------------------------------------------------------------------------

@dataclass
class PoHRuntime:
    """
    Thin runtime wrapper that can be used by other subsystems
    (e.g., juror consoles, onboarding flows) without needing
    to know about the underlying ledger layout.
    """

    # Reserved for future use (e.g., in-memory caches or additional queues)
    attached_at: float = field(default_factory=lambda: time.time())

    def status(self, user_id: str) -> Dict[str, Any]:
        """
        Return the current PoH status for a user, suitable for API responses.
        """
        rec = get_poh_record(user_id) or {
            "tier": 0,
            "revoked": False,
            "source": "unknown",
            "updated_at": None,
            "revocation_reason": None,
        }
        return {
            "user_id": user_id,
            "tier": int(rec.get("tier", 0)),
            "revoked": bool(rec.get("revoked", False)),
            "source": rec.get("source") or "unknown",
            "updated_at": rec.get("updated_at"),
            "revocation_reason": rec.get("revocation_reason"),
        }

    def t2_applications(self) -> Dict[str, Dict[str, Any]]:
        """
        Return all Tier-2 applications (shallow copy).
        """
        return get_t2_queue()

    def t2_get(self, account_id: str) -> Optional[Dict[str, Any]]:
        """
        Return a single Tier-2 application.
        """
        return get_t2_queue().get(account_id)

    def t2_submit(
        self,
        account_id: str,
        videos: Optional[List[str]] = None,
        title: str = "",
        desc: str = "",
    ) -> Dict[str, Any]:
        """
        Convenience wrapper for upsert_t2_application().
        """
        return upsert_t2_application(
            account_id=account_id,
            videos=videos,
            title=title,
            desc=desc,
        )

    def t2_vote(self, candidate_id: str, juror_id: str, approve: bool) -> Dict[str, Any]:
        """
        Convenience wrapper for register_t2_vote().
        """
        return register_t2_vote(
            candidate_id=candidate_id,
            juror_id=juror_id,
            approve=approve,
        )


# Provide a module-level runtime instance for convenience.
poh_runtime = PoHRuntime()
