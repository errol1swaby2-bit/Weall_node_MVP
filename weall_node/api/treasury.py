from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.api.strict import require_mutation_allowed
from weall_node.api.tx_helpers import apply_tx_local_atomic, make_envelope, next_nonce_for_user
from weall.v1 import tx_pb2

router = APIRouter(prefix="/treasury", tags=["treasury"])


def current_user_id_from_cookie_optional() -> Optional[str]:
    return None


def _require_auth(user_id: Optional[str]) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="auth_required")
    return str(user_id)


def _treasury_root() -> Dict[str, Any]:
    t = executor.ledger.setdefault("treasury", {"balance": 0, "history": []})
    if not isinstance(t, dict):
        executor.ledger["treasury"] = {"balance": 0, "history": []}
        t = executor.ledger["treasury"]
    t.setdefault("balance", 0)
    t.setdefault("history", [])
    return t


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


class Transfer(BaseModel):
    treasury_id: str = ""
    to_hex: str
    amount: int
    memo: str = ""


@router.get("/status")
def treasury_status():
    t = _treasury_root()
    return {"ok": True, "balance": int(t.get("balance", 0) or 0), "history": t.get("history", [])}


@router.post("/transfer")
def treasury_transfer(payload: Transfer, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    if int(payload.amount) <= 0:
        raise HTTPException(status_code=400, detail="amount_must_be_positive")

    treasury_id_b = _id_bytes(payload.treasury_id) if payload.treasury_id else b""
    to_b = _id_bytes(payload.to_hex)
    if not to_b:
        raise HTTPException(status_code=400, detail="to_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.treasury_transfer.treasury_id = treasury_id_b
        env.treasury_transfer.to = to_b
        env.treasury_transfer.amount = int(payload.amount)
        env.treasury_transfer.memo = payload.memo or ""

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_TREASURY_TRANSFER, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    return {"ok": True, "tx_id": bytes(env.tx_id).hex()}
