from __future__ import annotations
from fastapi import APIRouter, HTTPException
from . import poh as poh_api

try:
    from . import content as content_api  # optional; may not exist
except Exception:
    content_api = None  # type: ignore

router = APIRouter()


# Legacy: /poh/status?user_id=...
@router.get("/poh/status")
def compat_poh_status(user_id: str | None = None, user: str | None = None):
    u = user_id or user
    if not u:
        raise HTTPException(status_code=400, detail="user_id is required")
    return poh_api.status(u)


# Legacy aliases for content
@router.get("/content/list")
def compat_content_list():
    if not content_api or not hasattr(content_api, "feed"):
        raise HTTPException(status_code=404, detail="content feed not available")
    return content_api.feed()


@router.post("/content/create")
def compat_content_create(author: str, text: str):
    if not content_api or not hasattr(content_api, "post_content"):
        raise HTTPException(status_code=404, detail="content post not available")
    return content_api.post_content({"author": author, "text": text})
