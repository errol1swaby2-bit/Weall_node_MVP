# weall_node/api/recovery.py
from __future__ import annotations

"""
Account recovery API for WeAll.

This module defines a juror-backed recovery flow:

1. A user (or client on their behalf) submits a recovery request:
   - identifies the PoH / user_id
   - supplies a proposed new account public key
   - explains the reason / context

   -> This creates a "recovery case" in executor.ledger["recovery"]["cases"]
      with status "pending_jurors".

2. A juror process (off-chain worker or governance process) reviews the
   case and eventually calls the finalize endpoint with a decision.

3. On "grant", the PoH runtime's `rebind_account_key` is called to
   bind the new account key to the identity, and a recovery event is
   recorded.

Notes
-----
* This API does NOT attempt to implement the full question+answer
  derivation or cryptographic side of recovery just yet. It focuses on
  the "juror-backed case" plumbing and key rebind mechanics.

* Token economics and WCN are not touched here. Any penalties or
  rewards related to a fraudulent recovery attempt must be implemented
  in the reputation / governance / rewards layers.
"""

import secrets
import time
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..weall_runtime import poh as poh_rt

router = APIRouter(prefix="/recovery", tags=["recovery"])


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------


def _ensure_recovery_ledger() -> Dict[str, dict]:
    ledger = executor.ledger
    rec_ns = ledger.setdefault("recovery", {})
    rec_ns.setdefault("cases", {})
    rec_ns.setdefault("events", [])
    return rec_ns  # type: ignore[return-value]


def _now() -> float:
    return time.time()


def _new_case_id() -> str:
    return "reco-" + secrets.token_hex(8)


def _maybe_save_state() -> None:
    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RecoveryRequestCreate(BaseModel):
    user_id: str = Field(
        ...,
        description="User / PoH identifier for the identity requesting recovery.",
    )
    new_account_pk_hex: str = Field(
        ...,
        description="Proposed new account public key (Ed25519 hex).",
    )
    reason: str = Field(
        ...,
        max_length=4000,
        description="Human-readable explanation of the recovery request.",
    )


class RecoveryCase(BaseModel):
    case_id: str
    user_id: str
    poh_id: str
    new_account_pk_hex: str
    status: str
    reason: str
    created_at: float
    updated_at: float
    decision: Optional[str] = None
    decided_at: Optional[float] = None
    decided_by: Optional[str] = None  # panel identifier or process id
    evidence_root: Optional[str] = None


class RecoveryFinalizeRequest(BaseModel):
    decision: str = Field(
        ...,
        description='"grant" to approve recovery, "deny" to reject.',
    )
    decided_by: Optional[str] = Field(
        None,
        description="Optional identifier for the juror panel or authority making this decision.",
    )
    evidence_root: Optional[str] = Field(
        None,
        description="Optional IPFS / hash pointer to evidence bundle.",
    )
    # Optional: old_pk_hex for additional checking / logging
    claimed_old_pk_hex: Optional[str] = Field(
        None,
        description="Optional old account pk hex that the requester claims they lost.",
    )


class RecoveryCaseResponse(BaseModel):
    case: RecoveryCase


class RecoveryEvent(BaseModel):
    case_id: str
    user_id: str
    poh_id: str
    new_account_pk_hex: str
    decision: str
    at: float
    decided_by: Optional[str] = None
    evidence_root: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoint implementations
# ---------------------------------------------------------------------------


@router.post("/request", response_model=RecoveryCaseResponse)
def create_recovery_request(payload: RecoveryRequestCreate) -> RecoveryCaseResponse:
    """
    Create a new recovery case.

    Preconditions:
    - The target user must have a PoH record (tier >= 1).

    Effects:
    - A new recovery case is created with status "pending_jurors".
    """
    rec_ns = _ensure_recovery_ledger()
    poh_rec = poh_rt.ensure_poh_record(payload.user_id)
    if poh_rec.get("tier", 0) < 1:
        raise HTTPException(
            status_code=400,
            detail="User does not have a Tier-1 PoH record and cannot request recovery.",
        )

    case_id = _new_case_id()
    now = _now()
    case_rec = {
        "case_id": case_id,
        "user_id": payload.user_id,
        "poh_id": poh_rec.get("poh_id", payload.user_id),
        "new_account_pk_hex": payload.new_account_pk_hex,
        "status": "pending_jurors",
        "reason": payload.reason,
        "created_at": now,
        "updated_at": now,
        "decision": None,
        "decided_at": None,
        "decided_by": None,
        "evidence_root": None,
    }
    rec_ns["cases"][case_id] = case_rec
    _maybe_save_state()

    return RecoveryCaseResponse(case=RecoveryCase(**case_rec))


@router.get("/cases/{case_id}", response_model=RecoveryCaseResponse)
def get_recovery_case(case_id: str) -> RecoveryCaseResponse:
    """
    Fetch an existing recovery case by id.
    """
    rec_ns = _ensure_recovery_ledger()
    case_rec = rec_ns["cases"].get(case_id)
    if not case_rec:
        raise HTTPException(status_code=404, detail="Recovery case not found.")
    return RecoveryCaseResponse(case=RecoveryCase(**case_rec))


@router.post("/cases/{case_id}/finalize", response_model=RecoveryCaseResponse)
def finalize_recovery_case(
    case_id: str,
    payload: RecoveryFinalizeRequest,
) -> RecoveryCaseResponse:
    """
    Finalize a recovery case.

    - decision == "grant" :
        - PoH runtime `rebind_account_key` is called with the new
          account public key.
        - A recovery event is recorded.
        - Case status becomes "granted".

    - decision == "deny" :
        - Case status becomes "denied".

    This endpoint is expected to be called by a juror-backed process or
    admin tool, not arbitrary clients.
    """
    decision_norm = payload.decision.strip().lower()
    if decision_norm not in {"grant", "deny"}:
        raise HTTPException(
            status_code=400,
            detail='decision must be either "grant" or "deny".',
        )

    rec_ns = _ensure_recovery_ledger()
    case_rec = rec_ns["cases"].get(case_id)
    if not case_rec:
        raise HTTPException(status_code=404, detail="Recovery case not found.")

    if case_rec.get("status") not in {"pending_jurors"}:
        raise HTTPException(
            status_code=400,
            detail=f"Case is already finalized with status={case_rec.get('status')!r}.",
        )

    now = _now()
    case_rec["decision"] = decision_norm
    case_rec["decided_at"] = now
    case_rec["decided_by"] = payload.decided_by
    case_rec["evidence_root"] = payload.evidence_root

    if decision_norm == "grant":
        # Perform the key rebind in the PoH runtime
        poh_rt.rebind_account_key(
            case_rec["user_id"],
            old_pk_hex=payload.claimed_old_pk_hex,
            new_pk_hex=case_rec["new_account_pk_hex"],
            case_id=case_id,
        )
        case_rec["status"] = "granted"

        # Record a recovery event for auditability
        rec_ns["events"].append(
            {
                "case_id": case_id,
                "user_id": case_rec["user_id"],
                "poh_id": case_rec["poh_id"],
                "new_account_pk_hex": case_rec["new_account_pk_hex"],
                "decision": decision_norm,
                "at": now,
                "decided_by": payload.decided_by,
                "evidence_root": payload.evidence_root,
            }
        )
    else:
        case_rec["status"] = "denied"

    case_rec["updated_at"] = now
    _maybe_save_state()
    return RecoveryCaseResponse(case=RecoveryCase(**case_rec))
