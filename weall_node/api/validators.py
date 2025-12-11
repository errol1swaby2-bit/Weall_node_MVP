"""
weall_node/api/validators.py
--------------------------------------------------
MVP validator registry for WeAll Node, with role gating.

- Stores a simple set of validator records in the executor ledger
- Does NOT yet implement slashing, staking, or automatic selection
- Works alongside rewards pools, but does not modify them directly

API surface:

    GET  /validators/meta
        -> high-level overview (count, ids)

    GET  /validators
        -> full list of validator records

    POST /validators/register
        -> create or update a validator record
           (requires X-WeAll-User, PoH Tier-3, validator role enabled)

    DELETE /validators/{validator_id}
        -> remove a validator from the registry
           (requires X-WeAll-User, PoH Tier-3, and ownership of the record)
"""

import time
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Depends, Header, status
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/validators", tags=["validators"])


# ============================================================
# Internal ledger helpers
# ============================================================

def _state() -> Dict[str, Any]:
    """
    Ensure the validators namespace exists in the ledger.

    Shape:

        executor.ledger["validators"] = {
            "validators": {
                "<id>": { ...ValidatorRecord... },
                ...
            }
        }
    """
    return executor.ledger.setdefault("validators", {"validators": {}})


def _validators() -> Dict[str, Dict[str, Any]]:
    st = _state()
    return st.setdefault("validators", {})


def _get_poh_tier(poh_id: str) -> int:
    """
    Look up the current PoH tier from the ledger.

    Returns 0 if no record exists or the record is malformed.
    """
    ledger = executor.ledger
    poh_root = ledger.setdefault("poh", {})
    records = poh_root.setdefault("records", {})
    rec = records.get(poh_id)
    if not rec:
        return 0
    try:
        return int(rec.get("tier", 0))
    except Exception:
        return 0


def _get_roles_record(poh_id: str) -> Dict[str, Any]:
    """
    Look up the roles record for a given PoH id.

    Layout (from roles API):

        executor.ledger["roles"]["by_poh"][poh_id] = {
            "poh_id": ...,
            "tier": int,
            "validator": { "enabled": bool, ... },
            "juror": { ... },
            "operator": { ... },
            ...
        }
    """
    ledger = executor.ledger
    roles_root = ledger.get("roles", {})
    by_poh = roles_root.get("by_poh", {})
    return by_poh.get(poh_id, {})


def _require_tier3_validator(
    x_weall_user: str = Header(
        ...,
        alias="X-WeAll-User",
        description="WeAll user identifier (e.g. '@handle' or wallet id).",
    )
) -> str:
    """
    Dependency: ensure caller is Tier-3 and validator role is enabled.

    - PoH Tier must be >= 3
    - If a roles record exists, `validator.enabled` must be True
    """
    poh_id = x_weall_user
    tier = _get_poh_tier(poh_id)

    if tier < 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PoH Tier 3 is required to register or manage validators",
        )

    roles_rec = _get_roles_record(poh_id)
    validator_conf = roles_rec.get("validator", {})

    # If a roles record exists at all and explicitly disables validator, block.
    if roles_rec and not validator_conf.get("enabled", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Validator role is disabled for this account. "
                "Enable it via /roles/me before registering validators."
            ),
        )

    return poh_id


# ============================================================
# Models
# ============================================================

class ValidatorRecord(BaseModel):
    id: str = Field(..., description="Validator identifier (eg. node id or handle)")
    user_id: Optional[str] = Field(
        default=None,
        description="Associated user handle, eg. '@errol1swaby2'",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata for this validator (device, region, etc.)",
    )
    status: str = Field(
        default="active",
        description="Status flag (active, paused, banned, etc.)",
    )
    created_at: float = Field(..., description="Unix timestamp when record was created")
    updated_at: float = Field(..., description="Last update timestamp")


class ValidatorRegisterRequest(BaseModel):
    id: str = Field(..., description="Validator identifier (eg. 'node:1827f5b1948ad5b7')")
    user_id: Optional[str] = Field(
        default=None,
        description="Optional associated user handle (will be validated against X-WeAll-User)",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form metadata",
    )
    status: Optional[str] = Field(
        default="active",
        description="Optional explicit status override",
    )


class ValidatorsMetaResponse(BaseModel):
    ok: bool = True
    count: int
    validator_ids: List[str]


class ValidatorsListResponse(BaseModel):
    ok: bool = True
    validators: List[ValidatorRecord]


class ValidatorSingleResponse(BaseModel):
    ok: bool = True
    validator: ValidatorRecord


class DeleteResponse(BaseModel):
    ok: bool = True
    deleted: str


# ============================================================
# Routes
# ============================================================

@router.get("/meta", response_model=ValidatorsMetaResponse)
def get_validators_meta() -> Dict[str, Any]:
    """
    High-level overview – how many validators exist and their IDs.
    """
    vals = _validators()
    ids = sorted(vals.keys())
    return {
        "ok": True,
        "count": len(ids),
        "validator_ids": ids,
    }


@router.get("", response_model=ValidatorsListResponse)
def list_validators() -> Dict[str, Any]:
    """
    Return all validator records.

    This is intentionally public: the validator set should be auditable.
    """
    vals = _validators()
    records = [ValidatorRecord(**v) for v in vals.values()]
    return {
        "ok": True,
        "validators": records,
    }


@router.post("/register", response_model=ValidatorSingleResponse)
def register_validator(
    payload: ValidatorRegisterRequest,
    poh_id: str = Depends(_require_tier3_validator),
) -> Dict[str, Any]:
    """
    Register or update a validator.

    Idempotent: calling it again with the same `id` will update metadata/status
    and bump `updated_at`.

    Security constraints:

    - Caller must be PoH Tier-3 (checked via X-WeAll-User header).
    - If a roles record exists, `validator.enabled` must be True.
    - Caller cannot register validators on behalf of another user.
    """
    vals = _validators()
    now = time.time()

    # Prevent spoofing: if payload.user_id is provided, it must match the caller.
    if payload.user_id is not None and payload.user_id != poh_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot register a validator on behalf of another user",
        )

    effective_user_id = payload.user_id or poh_id

    if payload.id in vals:
        rec = vals[payload.id]
        # Update existing record
        rec["user_id"] = effective_user_id or rec.get("user_id")
        rec["metadata"] = payload.metadata or rec.get("metadata", {})
        if payload.status is not None:
            rec["status"] = payload.status
        rec["updated_at"] = now
    else:
        # Create new record
        rec = ValidatorRecord(
            id=payload.id,
            user_id=effective_user_id,
            metadata=payload.metadata,
            status=payload.status or "active",
            created_at=now,
            updated_at=now,
        ).dict()
        vals[payload.id] = rec

    return {
        "ok": True,
        "validator": ValidatorRecord(**rec),
    }


@router.delete("/{validator_id}", response_model=DeleteResponse)
def delete_validator(
    validator_id: str,
    poh_id: str = Depends(_require_tier3_validator),
) -> Dict[str, Any]:
    """
    Remove a validator from the registry.

    Security constraints:

    - Caller must be PoH Tier-3 (checked via X-WeAll-User header).
    - If the record has a `user_id`, it must match the caller's PoH id.
      (Prevents random Tier-3s from deleting others' validators.)
    """
    vals = _validators()
    if validator_id not in vals:
        raise HTTPException(status_code=404, detail="Validator not found")

    rec = vals[validator_id]
    owner = rec.get("user_id")

    if owner is not None and owner != poh_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete validators you own",
        )

    vals.pop(validator_id)
    return {"ok": True, "deleted": validator_id}
