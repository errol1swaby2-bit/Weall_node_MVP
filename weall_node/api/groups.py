from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.api.strict import require_mutation_allowed
from weall_node.api.tx_helpers import apply_tx_local_atomic, make_envelope, next_nonce_for_user
from weall.v1 import tx_pb2

router = APIRouter(prefix="/groups", tags=["groups"])


def current_user_id_from_cookie_optional() -> Optional[str]:
    return None


def _require_auth(user_id: Optional[str]) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="auth_required")
    return str(user_id)


def _groups_root() -> Dict[str, Any]:
    g = executor.ledger.setdefault("groups", {})
    if not isinstance(g, dict):
        executor.ledger["groups"] = {}
        g = executor.ledger["groups"]
    g.setdefault("by_id", {})
    g.setdefault("members", {})
    return g


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


class GroupCreate(BaseModel):
    display_name: str
    description: str = ""


class GroupRef(BaseModel):
    group_id: str


@router.get("/list")
def list_groups():
    g = _groups_root()
    by_id = g.get("by_id", {})
    if not isinstance(by_id, dict):
        by_id = {}
    return {"ok": True, "groups": list(by_id.values())}


@router.post("/create")
def create_group(payload: GroupCreate, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    if not payload.display_name.strip():
        raise HTTPException(status_code=400, detail="display_name_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.group_create.display_name = payload.display_name
        env.group_create.description = payload.description or ""

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_GROUP_CREATE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    gid = bytes(env.tx_id).hex()
    return {"ok": True, "group_id": gid}


@router.post("/join")
def join_group(payload: GroupRef, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    gid_b = _id_bytes(payload.group_id)
    if not gid_b:
        raise HTTPException(status_code=400, detail="group_id_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.group_join.group_id = gid_b

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_GROUP_JOIN, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))
    return {"ok": True}


@router.post("/leave")
def leave_group(payload: GroupRef, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    gid_b = _id_bytes(payload.group_id)
    if not gid_b:
        raise HTTPException(status_code=400, detail="group_id_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.group_leave.group_id = gid_b

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_GROUP_LEAVE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))
    return {"ok": True}
