from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.api.strict import require_mutation_allowed
from weall_node.api.tx_helpers import apply_tx_local_atomic, make_envelope, next_nonce_for_user, sender_bytes_from_user_id
from weall.v1 import common_pb2, tx_pb2

router = APIRouter(prefix="/content", tags=["content"])


def current_user_id_from_cookie_optional() -> Optional[str]:
    return None


def _require_auth(user_id: Optional[str]) -> str:
    if not user_id:
        raise HTTPException(status_code=401, detail="auth_required")
    return str(user_id)


def _poh_tier_for(user_id: str) -> int:
    poh = executor.ledger.get("poh", {})
    if not isinstance(poh, dict):
        return 0
    recs = poh.get("records", {})
    if not isinstance(recs, dict):
        return 0
    sender_hex = sender_bytes_from_user_id(user_id).hex()
    r = recs.get(sender_hex, {})
    if not isinstance(r, dict):
        return 0
    return int(r.get("tier", 0) or 0)


def require_like_comment(tier: int) -> None:
    if int(tier) < 1:
        raise HTTPException(status_code=403, detail="tier_required_like_comment")


def require_posting(tier: int) -> None:
    if int(tier) < 2:
        raise HTTPException(status_code=403, detail="tier_required_post")


def _content_root() -> Dict[str, Any]:
    c = executor.ledger.setdefault("content", {})
    if not isinstance(c, dict):
        executor.ledger["content"] = {}
        c = executor.ledger["content"]
    c.setdefault("posts", [])
    c.setdefault("likes", {})
    c.setdefault("comments", {})
    return c


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


class PostCreate(BaseModel):
    title: str = ""
    summary: str = ""
    mime: str = "text/plain"


class LikeBody(BaseModel):
    post: str


class CommentBody(BaseModel):
    post: str
    text: str


@router.get("/feed")
def feed(limit: int = 50):
    c = _content_root()
    posts = c.get("posts", [])
    if not isinstance(posts, list):
        posts = []
    return {"ok": True, "posts": list(reversed(posts))[: max(1, int(limit))]}


@router.post("/post")
def create_post(payload: PostCreate, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    tier = _poh_tier_for(uid)
    require_posting(tier)

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.content_post.content_ref.CopyFrom(common_pb2.Ref(kind="none", value=""))
        env.content_post.mime = payload.mime or "text/plain"
        env.content_post.title = payload.title or ""
        env.content_post.summary = payload.summary or ""

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_CONTENT_POST, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    post_id = bytes(env.tx_id).hex()
    return {"ok": True, "post_id": post_id}


@router.post("/like")
def like(body: LikeBody, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    tier = _poh_tier_for(uid)
    require_like_comment(tier)

    post_b = _id_bytes(body.post)
    if not post_b:
        raise HTTPException(status_code=400, detail="post_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.like.content_id = post_b

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_LIKE, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))
    return {"ok": True}


@router.post("/comment")
def comment(body: CommentBody, user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)):
    uid = _require_auth(user_id)
    require_mutation_allowed(uid)

    tier = _poh_tier_for(uid)
    require_like_comment(tier)

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="comment_text_required")

    post_b = _id_bytes(body.post)
    if not post_b:
        raise HTTPException(status_code=400, detail="post_required")

    nonce = next_nonce_for_user(executor, uid)

    def _fill(env: tx_pb2.TxEnvelope) -> None:
        env.comment.content_id = post_b
        env.comment.text = body.text
        env.comment.comment_ref.CopyFrom(common_pb2.Ref(kind="none", value=""))

    env = make_envelope(user_id=uid, tx_type=tx_pb2.TX_COMMENT, nonce=nonce, fill_payload=_fill)
    ok, receipt = apply_tx_local_atomic(executor, env)
    if not ok:
        raise HTTPException(status_code=400, detail=receipt.get("error", "tx_failed"))

    comment_id = bytes(env.tx_id).hex()
    return {"ok": True, "comment_id": comment_id}
