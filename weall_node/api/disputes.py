from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.api.strict import require_mutation_allowed
from weall_node.api.tx_helpers import apply_tx_local_atomic, make_envelope, next_nonce_for_user
from weall.v1 import common_pb2, tx_pb2

router = APIRouter(prefix="/disputes", tags=["disputes"])


def current_user_id_from_cookie_optional() -> Optional[str]:
    return None


def _require_auth(user_id: Optional[str]) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="auth_required")
    return str(user_id)


def _root() -> Dict[str, Any]:
    d = executor.ledger.setdefault("disputes", {})
    if not isinstance(d, dict):
        executor.ledger["disputes"] = {}
        d = executor.ledger["disputes"]
    d.setdefault("by_id", {})
    return d


def _id_bytes(s: str) -> bytes:
    s = (s or "").strip()
    if not s:
        return b""
    h = s.lower()
    if all(c in "0123456789abcdef" for c in h) and len(h) % 2 == 0:
        try:
            return bytes.fromhex(h)
        except Exception:
            pass
    return s.encode("utf-8")


class DisputeOpen(BaseModel):
    kind: str = "generic"
    claim: str
    scope_id: str = ""
    target_id: str = ""


class EvidenceSubmit(BaseModel):
    dispute_id: str
    note: str = ""
    evidence_kind: str = "none"
    evidence_value: str = ""


class JurorVote(BaseModel):
    dispute_id: str
    support_claim: bool
    note: str = ""


class DisputeRef(BaseModel):
    dispute_id: str


@router.get("/list")
def list_disputes():
    r = _root()
    by_id = r.get("by_id", {})
    if not isinstance(by_id, dict):
        by_id = {}
    return {"ok": True, "disputes": list(by_id.values())}


@router.post("/open")
def open_dispute(payload: DisputeOpen, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    if not payload.claim.strip():
        raise HTTPException(status_code=400, detail="claim_required")

    nonce = next_nonce_for_user(executor, uid)
    scope_b = _id_bytes(payload.scope_id)
    target_b = _id_bytes(payload.target_id)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.dispute_open.scope_id = scope_b
        env.dispute_open.target_id = target_b
        env.dispute_open.kind = (payload.kind or "generic").strip()
        env.dispute_open.claim = payload.claim

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_DISPUTE_OPEN, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    dispute_id = bytes(env.tx_id).hex()
    return {"ok": True, "dispute_id": dispute_id}


@router.post("/evidence")
def submit_evidence(payload: EvidenceSubmit, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    did_b = _id_bytes(payload.dispute_id)
    if not did_b:
        raise HTTPException(status_code=400, detail="dispute_id_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.dispute_submit_evidence.dispute_id = did_b
        env.dispute_submit_evidence.note = payload.note or ""
        env.dispute_submit_evidence.evidence_ref.CopyFrom(
            common_pb2.Ref(kind=(payload.evidence_kind or "none"), value=(payload.evidence_value or ""))
        )

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_DISPUTE_SUBMIT_EVIDENCE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))
    return {"ok": True}


@router.post("/juror_vote")
def juror_vote(payload: JurorVote, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    did_b = _id_bytes(payload.dispute_id)
    if not did_b:
        raise HTTPException(status_code=400, detail="dispute_id_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.dispute_juror_vote.dispute_id = did_b
        env.dispute_juror_vote.support_claim = bool(payload.support_claim)
        env.dispute_juror_vote.note = payload.note or ""

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_DISPUTE_JUROR_VOTE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))
    return {"ok": True}


@router.post("/finalize")
def finalize_dispute(payload: DisputeRef, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    did_b = _id_bytes(payload.dispute_id)
    if not did_b:
        raise HTTPException(status_code=400, detail="dispute_id_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.dispute_finalize.dispute_id = did_b

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_DISPUTE_FINALIZE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))
    return {"ok": True}
