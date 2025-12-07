"""
weall_node/api/validators.py
--------------------------------------------------
MVP validator registry for WeAll Node.

- Stores a simple set of validator records in the executor ledger
- Does NOT yet implement slashing, staking, or automatic selection
- Works alongside rewards pools, but does not modify them directly

API surface:

    GET  /validators/meta
        -> high-level overview (count, ids)

    GET  /validators
        -> full list of validator records

    POST /validators/register
        -> register or update a validator record

    DELETE /validators/{validator_id}
        -> remove a validator from the registry
"""

import time
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/validators", tags=["validators"])


# ============================================================
# Ledger helpers
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


# ============================================================
# Models
# ============================================================

class ValidatorRecord(BaseModel):
    id: str = Field(..., description="Validator identifier (eg. node id or handle)")
    user_id: Optional[str] = Field(
        default=None,
        description="Associated user handle, eg. '@errol1swaby2'"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata for this validator (device, region, etc.)"
    )
    status: str = Field(
        default="active",
        description="Status flag (active, paused, banned, etc.)"
    )
    created_at: float = Field(..., description="Unix timestamp when record was created")
    updated_at: float = Field(..., description="Last update timestamp")


class ValidatorRegisterRequest(BaseModel):
    id: str = Field(..., description="Validator identifier (eg. 'node:1827f5b1948ad5b7')")
    user_id: Optional[str] = Field(
        default=None,
        description="Optional associated user handle"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form metadata"
    )
    status: Optional[str] = Field(
        default="active",
        description="Optional explicit status override"
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
def validators_meta() -> Dict[str, Any]:
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
    """
    vals = _validators()
    records = [ValidatorRecord(**v) for v in vals.values()]
    return {
        "ok": True,
        "validators": records,
    }


@router.post("/register", response_model=ValidatorSingleResponse)
def register_validator(payload: ValidatorRegisterRequest) -> Dict[str, Any]:
    """
    Register or update a validator.

    Idempotent: calling it again with the same `id` will update metadata/status
    and bump `updated_at`.
    """
    vals = _validators()
    now = time.time()

    if payload.id in vals:
        rec = vals[payload.id]
        # Update existing record
        rec["user_id"] = payload.user_id or rec.get("user_id")
        rec["metadata"] = payload.metadata or rec.get("metadata", {})
        if payload.status is not None:
            rec["status"] = payload.status
        rec["updated_at"] = now
    else:
        # Create new record
        rec = ValidatorRecord(
            id=payload.id,
            user_id=payload.user_id,
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
def delete_validator(validator_id: str) -> Dict[str, Any]:
    """
    Remove a validator from the registry.
    """
    vals = _validators()
    if validator_id not in vals:
        raise HTTPException(status_code=404, detail="Validator not found")

    vals.pop(validator_id)
    return {"ok": True, "deleted": validator_id}
