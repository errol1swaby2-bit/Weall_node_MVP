"""
weall_node/api/content.py
-------------------------

Content API (MVP → spec-aligned tiers)

Storage:
- Posts / likes / comments / media index are stored in executor.ledger["content"].
- executor.save_state() is called on writes so content persists.

PoH tier gates (per spec):
- Tier 1: view only
- Tier 2: like + comment
- Tier 3: create posts + upload media
Moderation is handled via dispute flow (no centralized admin deletes here).
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from starlette.responses import Response

from ..security.current_user import current_user_id_from_cookie_optional
from ..weall_executor import executor
from ..weall_runtime.storage import get_client as get_storage_client
from . import roles as roles_api


router = APIRouter()
_LOCK = threading.RLock()

SCOPE_GLOBAL = "global"
SCOPE_GROUP = "group"


# ============================================================
# Models
# ============================================================

class MediaRef(BaseModel):
    cid: str = Field(..., min_length=4, max_length=200)
    mime: Optional[str] = Field(None, max_length=120)


class PostCreate(BaseModel):
    """Payload used when creating a new post (Tier 3)."""
    author: str = Field(..., description="@handle of the author (must match session user_id)")
    text: str = Field(..., max_length=4000)
    scope: Literal["global", "group"] = Field(
        "global",
        description="Post visibility scope: 'global' or 'group'.",
    )
    group_id: Optional[str] = Field(
        None,
        description="Required when scope='group'.",
    )
    media: Optional[List[MediaRef]] = Field(
        default=None,
        description="Optional media references (CIDs). Upload via /content/upload first.",
    )


class CommentCreate(BaseModel):
    text: str = Field(..., max_length=2000)


class UploadResponse(BaseModel):
    ok: bool = True
    cid: str
    mime: Optional[str] = None
    bytes: int
    pinned: bool = False


# ============================================================
# Auth / tier helpers
# ============================================================

async def _resolve_user_id(
    session_user_id: Optional[str] = Depends(current_user_id_from_cookie_optional),
    x_weall_user: Optional[str] = Header(
        default=None,
        alias="X-WeAll-User",
        description="Legacy identity header (dev-only). Prefer cookie session.",
    ),
) -> Optional[str]:
    return session_user_id or x_weall_user


def _require_min_tier(min_tier: int):
    async def dep(user_id: Optional[str] = Depends(_resolve_user_id)) -> str:
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )
        prof = roles_api.get_effective_profile_for_user(user_id)
        if int(getattr(prof, "poh_tier", 0)) < int(min_tier):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires PoH Tier {min_tier}+.",
            )
        return user_id
    return dep


# ============================================================
# Internal state helpers
# ============================================================

def _init_content_state() -> Dict[str, Any]:
    """
    Ensure the 'content' namespace exists in the ledger and normalize structures.
    """
    with _LOCK:
        if "content" not in executor.ledger or not isinstance(executor.ledger.get("content"), dict):
            executor.ledger["content"] = {}

        c = executor.ledger["content"]

        # posts: list[dict]
        posts = c.get("posts")
        if posts is None:
            c["posts"] = []
        elif isinstance(posts, dict):
            # legacy dict -> list
            c["posts"] = list(posts.values())
        elif not isinstance(posts, list):
            c["posts"] = []

        # likes: {post_id: {user_id: ts}}
        if not isinstance(c.get("likes"), dict):
            c["likes"] = {}

        # comments: {post_id: [comment_dict]}
        if not isinstance(c.get("comments"), dict):
            c["comments"] = {}

        # media index: {cid: {mime, bytes, created_at, created_by}}
        if not isinstance(c.get("media"), dict):
            c["media"] = {}

        return c


def _get_post_by_id(state: Dict[str, Any], post_id: str) -> Dict[str, Any]:
    for p in state.get("posts", []):
        if p.get("id") == post_id:
            return p
    raise HTTPException(status_code=404, detail="Post not found.")


def _decorate_post(state: Dict[str, Any], post: Dict[str, Any], viewer_id: Optional[str]) -> Dict[str, Any]:
    pid = post.get("id")
    likes = state.get("likes", {}).get(pid, {}) or {}
    comments = state.get("comments", {}).get(pid, []) or []
    me_liked = False
    if viewer_id and isinstance(likes, dict):
        me_liked = viewer_id in likes

    out = dict(post)
    out["like_count"] = len(likes) if isinstance(likes, dict) else 0
    out["comment_count"] = len(comments) if isinstance(comments, list) else 0
    out["me_liked"] = bool(me_liked)
    return out


def _scope_guard_for_view(post_or_scope: Dict[str, Any] | str, viewer_id: Optional[str], group_id: Optional[str] = None) -> None:
    """
    Enforce Tier-1+ for group content viewing.
    - Global scope is always viewable.
    - Group scope requires an authenticated user with Tier >= 1.
    """
    if isinstance(post_or_scope, str):
        scope = post_or_scope
        gid = group_id
    else:
        scope = post_or_scope.get("scope") or SCOPE_GLOBAL
        gid = post_or_scope.get("group_id")

    if scope != SCOPE_GROUP:
        return

    if not viewer_id:
        raise HTTPException(status_code=401, detail="Not authenticated (group scope).")

    prof = roles_api.get_effective_profile_for_user(viewer_id)
    if int(getattr(prof, "poh_tier", 0)) < 1:
        raise HTTPException(status_code=403, detail="Requires PoH Tier 1+ to view group content.")

    if not gid:
        raise HTTPException(status_code=400, detail="group_id required for group scope.")


def _save() -> None:
    try:
        executor.save_state()
    except Exception:
        pass


# ============================================================
# Endpoints
# ============================================================

@router.get("/content/meta")
def get_content_meta() -> Dict[str, Any]:
    state = _init_content_state()
    return {
        "ok": True,
        "version": "mvp+likes+comments+uploads",
        "max_post_length": 4000,
        "max_comment_length": 2000,
        "scopes": ["global", "group"],
        "counts": {
            "posts": len(state.get("posts", [])),
            "media": len(state.get("media", {})),
        },
        "tier_gates": {
            "view": 1,
            "like_comment": 2,
            "post_upload": 3,
        },
        "notes": "Moderation is via dispute flow; this API does not admin-delete content.",
    }


@router.get("/content/posts")
def list_posts(
    scope: Literal["global", "group"] = Query("global", description="Scope filter."),
    group_id: Optional[str] = Query(None, description="Required when scope='group'."),
    viewer_id: Optional[str] = Depends(_resolve_user_id),
) -> Dict[str, Any]:
    state = _init_content_state()

    _scope_guard_for_view(scope, viewer_id, group_id=group_id)

    posts = list(state.get("posts", []))
    if scope == SCOPE_GROUP:
        posts = [p for p in posts if p.get("scope") == SCOPE_GROUP and p.get("group_id") == group_id]
    else:
        posts = [p for p in posts if p.get("scope") == SCOPE_GLOBAL]

    posts.sort(key=lambda p: int(p.get("created_at", 0) or 0), reverse=True)
    return {"ok": True, "scope": scope, "group_id": group_id, "posts": [_decorate_post(state, p, viewer_id) for p in posts]}


@router.post("/content/posts")
def create_post(
    payload: PostCreate,
    user_id: str = Depends(_require_min_tier(3)),
) -> Dict[str, Any]:
    state = _init_content_state()

    scope = payload.scope or SCOPE_GLOBAL
    group_id = payload.group_id

    if scope == SCOPE_GROUP and not group_id:
        raise HTTPException(status_code=400, detail="group_id required when scope='group'.")

    if payload.author and payload.author != user_id:
        raise HTTPException(status_code=403, detail="author must match authenticated user_id.")

    now = int(time.time())
    post_id = secrets.token_hex(8)

    post = {
        "id": post_id,
        "author": user_id,
        "text": payload.text,
        "scope": scope,
        "group_id": group_id,
        "media": [m.model_dump() for m in (payload.media or [])],
        "created_at": now,
        "updated_at": now,
    }

    with _LOCK:
        posts = list(state.get("posts", []))
        posts.append(post)
        state["posts"] = posts

    try:
        if hasattr(executor, "add_creator_ticket"):
            executor.add_creator_ticket(user_id, weight=1.0)
    except Exception:
        pass

    _save()
    return {"ok": True, "post": _decorate_post(state, post, user_id)}


@router.get("/content/feed")
def get_feed(
    scope: Literal["global", "group"] = Query("global", description="Feed scope."),
    group_id: Optional[str] = Query(None, description="Group feed when scope == 'group'."),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of posts to return."),
    viewer_id: Optional[str] = Depends(_resolve_user_id),
) -> Dict[str, Any]:
    state = _init_content_state()

    _scope_guard_for_view(scope, viewer_id, group_id=group_id)

    posts = list(state.get("posts", []))
    if scope == SCOPE_GROUP:
        posts = [p for p in posts if p.get("scope") == SCOPE_GROUP and p.get("group_id") == group_id]
    else:
        posts = [p for p in posts if p.get("scope") == SCOPE_GLOBAL]

    posts.sort(key=lambda p: int(p.get("created_at", 0) or 0), reverse=True)
    posts = posts[:limit]

    return {
        "ok": True,
        "scope": scope,
        "group_id": group_id,
        "posts": [_decorate_post(state, p, viewer_id) for p in posts],
    }


# ----------------------------
# Likes (Tier 2+)
# ----------------------------

@router.post("/content/posts/{post_id}/like")
def like_post(
    post_id: str,
    user_id: str = Depends(_require_min_tier(2)),
) -> Dict[str, Any]:
    state = _init_content_state()
    post = _get_post_by_id(state, post_id)

    _scope_guard_for_view(post, user_id)

    with _LOCK:
        likes = state["likes"].setdefault(post_id, {})
        if not isinstance(likes, dict):
            likes = {}
            state["likes"][post_id] = likes
        likes[user_id] = int(time.time())

    _save()
    return {"ok": True, "post_id": post_id, "like_count": len(state["likes"].get(post_id, {})), "me_liked": True}


@router.delete("/content/posts/{post_id}/like")
def unlike_post(
    post_id: str,
    user_id: str = Depends(_require_min_tier(2)),
) -> Dict[str, Any]:
    state = _init_content_state()
    post = _get_post_by_id(state, post_id)
    _scope_guard_for_view(post, user_id)

    with _LOCK:
        likes = state.get("likes", {}).get(post_id, {})
        if isinstance(likes, dict) and user_id in likes:
            del likes[user_id]

    _save()
    likes = state.get("likes", {}).get(post_id, {})
    return {"ok": True, "post_id": post_id, "like_count": len(likes) if isinstance(likes, dict) else 0, "me_liked": False}


# ----------------------------
# Comments (Tier 2+ to write)
# ----------------------------

@router.get("/content/posts/{post_id}/comments")
def list_comments(
    post_id: str,
    limit: int = Query(100, ge=1, le=500),
    viewer_id: Optional[str] = Depends(_resolve_user_id),
) -> Dict[str, Any]:
    state = _init_content_state()
    post = _get_post_by_id(state, post_id)
    _scope_guard_for_view(post, viewer_id)

    comments = list(state.get("comments", {}).get(post_id, []) or [])
    comments.sort(key=lambda c: int(c.get("created_at", 0) or 0))
    return {"ok": True, "post_id": post_id, "comments": comments[:limit]}


@router.post("/content/posts/{post_id}/comments")
def create_comment(
    post_id: str,
    payload: CommentCreate,
    user_id: str = Depends(_require_min_tier(2)),
) -> Dict[str, Any]:
    state = _init_content_state()
    post = _get_post_by_id(state, post_id)
    _scope_guard_for_view(post, user_id)

    now = int(time.time())
    comment = {
        "id": secrets.token_hex(10),
        "post_id": post_id,
        "author": user_id,
        "text": payload.text,
        "created_at": now,
    }

    with _LOCK:
        lst = state["comments"].setdefault(post_id, [])
        if not isinstance(lst, list):
            lst = []
            state["comments"][post_id] = lst
        lst.append(comment)

    _save()
    return {"ok": True, "comment": comment, "comment_count": len(state["comments"].get(post_id, []))}


# ----------------------------
# Media upload (Tier 3+)
# ----------------------------

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB (safe default for Termux)


@router.post("/content/upload", response_model=UploadResponse)
async def upload_media(
    file: UploadFile = File(...),
    user_id: str = Depends(_require_min_tier(3)),
) -> UploadResponse:
    if not file:
        raise HTTPException(status_code=400, detail="file required.")

    data = await file.read()
    if data is None:
        raise HTTPException(status_code=400, detail="empty upload.")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (>{_MAX_UPLOAD_BYTES} bytes).")

    mime = file.content_type or "application/octet-stream"

    ipfs = get_storage_client()
    cid = ipfs.add_bytes(data)

    pinned = False
    try:
        ipfs.pin_add(cid)
        pinned = True
    except Exception:
        pinned = False

    state = _init_content_state()
    with _LOCK:
        state["media"][cid] = {
            "cid": cid,
            "mime": mime,
            "bytes": len(data),
            "created_at": int(time.time()),
            "created_by": user_id,
            "filename": file.filename,
        }

    _save()
    return UploadResponse(ok=True, cid=cid, mime=mime, bytes=len(data), pinned=pinned)


@router.get("/content/media/{cid}")
def get_media(cid: str) -> Response:
    """
    Convenience endpoint to fetch bytes for a CID via the node storage client.
    (Works in both real IPFS and in-memory fallback mode.)
    """
    ipfs = get_storage_client()
    blob = ipfs.get(cid)
    if blob is None:
        raise HTTPException(status_code=404, detail="CID not found on this node.")

    state = _init_content_state()
    meta = state.get("media", {}).get(cid, {}) if isinstance(state.get("media"), dict) else {}
    media_type = meta.get("mime") or "application/octet-stream"
    return Response(content=blob, media_type=media_type)
