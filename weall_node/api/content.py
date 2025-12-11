"""
weall_node/api/content.py
-------------------------

MVP content API for WeAll Node.

- Stores posts in executor.ledger["content"]["posts"]
- Supports simple text posts with "global" or "group" scope
- Exposes:
    GET  /content/meta
    GET  /content/posts
    POST /content/posts
    GET  /content/feed
"""

import time
import secrets
from typing import List, Optional, Literal, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter()


# ============================================================
# Models
# ============================================================

class PostCreate(BaseModel):
    """Payload used when creating a new post."""
    author: str = Field(..., description="@handle of the author")
    text: str = Field(..., max_length=4000)
    scope: Literal["global", "group"] = Field(
        "global",
        description="Post visibility scope: 'global' or 'group'.",
    )
    group_id: Optional[str] = Field(
        None,
        description="Required when scope='group'.",
    )


# ============================================================
# Internal helpers
# ============================================================

def _normalize_post(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize any legacy post dicts into the current shape.

    We tolerate older keys like 'user', 'body', 'description', 'timestamp', etc.
    If something is missing, we fill in minimally so it won't crash the API.
    """
    if not isinstance(raw, dict):
        return {}

    now = int(time.time())

    author = raw.get("author") or raw.get("user") or "@unknown"
    text = (
        raw.get("text")
        or raw.get("body")
        or raw.get("description")
        or raw.get("title")
        or ""
    )

    scope = raw.get("scope") or "global"
    group_id = raw.get("group_id")

    created_at = int(raw.get("created_at") or raw.get("timestamp") or now)
    updated_at = int(raw.get("updated_at") or created_at)

    post_id = raw.get("id") or secrets.token_hex(8)

    return {
        "id": post_id,
        "author": author,
        "text": text,
        "scope": scope,
        "group_id": group_id,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _init_content_state() -> Dict[str, Any]:
    """
    Ensure the 'content' namespace exists in the ledger and normalize posts.

    This is idempotent and safe to call on every request.
    """
    state = executor.ledger.setdefault("content", {})
    posts_raw: List[Dict[str, Any]] = state.setdefault("posts", [])

    normalized: List[Dict[str, Any]] = []
    for p in posts_raw:
        norm = _normalize_post(p)
        if norm:
            normalized.append(norm)

    # overwrite only if shape changed / to guarantee normalized form
    state["posts"] = normalized
    return state


# ============================================================
# Routes
# ============================================================

@router.get("/content/meta")
def get_content_meta() -> Dict[str, Any]:
    """Return basic metadata about the content subsystem."""
    _init_content_state()
    return {
        "ok": True,
        "scopes": ["global", "group"],
        "max_post_length": 4000,
        "notes": "MVP content API; NFTs and media uploads will be layered on later.",
    }


@router.get("/content/posts")
def list_posts(
    scope: str = Query(
        "global",
        description="Scope filter: 'global' or 'group'.",
    ),
    group_id: Optional[str] = Query(
        None,
        description="Filter by group_id when scope == 'group'.",
    ),
) -> Dict[str, Any]:
    """
    List posts.

    - scope='global' returns all global posts.
    - scope='group' requires group_id and returns posts for that group.
    """
    state = _init_content_state()
    posts: List[Dict[str, Any]] = state.get("posts", [])

    if scope not in ("global", "group"):
        raise HTTPException(status_code=400, detail="invalid_scope")

    if scope == "global":
        filtered = [p for p in posts if p.get("scope") == "global"]
    else:
        if not group_id:
            raise HTTPException(status_code=400, detail="group_id_required")
        filtered = [
            p
            for p in posts
            if p.get("scope") == "group" and p.get("group_id") == group_id
        ]

    # newest first
    filtered.sort(key=lambda p: p.get("created_at", 0), reverse=True)

    return {
        "ok": True,
        "posts": filtered,
    }


@router.post("/content/posts")
def create_post(payload: PostCreate) -> Dict[str, Any]:
    """
    Create a new text post.

    For group-scoped posts, payload.group_id must be set.
    """
    state = _init_content_state()
    posts: List[Dict[str, Any]] = state.get("posts", [])

    if payload.scope == "group" and not payload.group_id:
        raise HTTPException(status_code=400, detail="group_id_required")

    now = int(time.time())
    post_id = secrets.token_hex(8)

    post = {
        "id": post_id,
        "author": payload.author,
        "text": payload.text,
        "scope": payload.scope,
        "group_id": payload.group_id,
        "created_at": now,
        "updated_at": now,
    }

    posts.append(post)
    state["posts"] = posts

    # Creator rewards: give the author a creator ticket for new content.
    # This does NOT mint coins; it only records a ticket in the WeCoin
    # 'creators' pool. Any errors are swallowed so we never break posting.
    try:
        if hasattr(executor, "add_creator_ticket"):
            executor.add_creator_ticket(payload.author, weight=1.0)
    except Exception:
        pass

    # We rely on the executor's own persistence; no explicit save() call here.
    return {
        "ok": True,
        "post": post,
    }


@router.get("/content/feed")
def get_feed(
    scope: str = Query(
        "global",
        description="Feed scope: 'global' or 'group'.",
    ),
    group_id: Optional[str] = Query(
        None,
        description="Group feed when scope == 'group'.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
        description="Maximum number of posts to return.",
    ),
) -> Dict[str, Any]:
    """
    Simple feed endpoint.

    Right now this is just a sorted slice of posts. Later we can plug in
    ranking, personalization, and NFT/media decoration.
    """
    state = _init_content_state()
    posts: List[Dict[str, Any]] = state.get("posts", [])

    if scope not in ("global", "group"):
        raise HTTPException(status_code=400, detail="invalid_scope")

    if scope == "global":
        filtered = [p for p in posts if p.get("scope") == "global"]
    else:
        if not group_id:
            raise HTTPException(status_code=400, detail="group_id_required")
        filtered = [
            p
            for p in posts
            if p.get("scope") == "group" and p.get("group_id") == group_id
        ]

    # newest first
    filtered.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    limited = filtered[:limit]

    return {
        "ok": True,
        "scope": scope,
        "group_id": group_id,
        "posts": limited,
    }
