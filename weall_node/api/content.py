"""
weall_node/api/content.py
--------------------------------------------------
Content posting + simple feed and media upload.
"""

import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..weall_executor import executor

# IMPORTANT: prefix so routes are /content/feed, /content/post, /content/upload
router = APIRouter(prefix="/content")


# ---------- Internal helpers ----------


def _ledger():
    # Single shared runtime ledger
    return getattr(executor, "ledger", {})


def _posts_list():
    """
    Backwards-compatible: support both
    - ledger["posts"] (older builds)
    - ledger["content"]["posts"] (newer layout)
    """
    ledger = _ledger()

    # Prefer legacy top-level "posts" if present
    if "posts" in ledger and isinstance(ledger["posts"], list):
        return ledger["posts"]

    content = ledger.get("content")
    if not isinstance(content, dict):
        content = {}
        ledger["content"] = content

    posts = content.get("posts")
    if not isinstance(posts, list):
        posts = []
        content["posts"] = posts

    return posts


def _append_post(p: dict):
    p = dict(p or {})
    p.setdefault("id", str(uuid.uuid4()))
    ts = int(time.time())
    # keep old key plus new ones the frontend reads
    p.setdefault("ts", ts)
    p.setdefault("time", ts)
    p.setdefault("created_at", ts)

    posts = _posts_list()
    posts.append(p)

    # persist via executor
    try:
        executor.save_state()
    except Exception:
        # non-fatal in case executor wiring changes
        pass

    return p


# ---------- Models ----------


class NewPost(BaseModel):
    author: str
    text: str
    tags: Optional[List[str]] = None
    media_url: Optional[str] = None
    content_type: Optional[str] = None


# ---------- Routes ----------


@router.get("/feed")
def get_feed(limit: int = 50):
    """
    Simple chronological feed; newest first.
    """
    posts = list(_posts_list())
    # sort by time/ts descending
    posts.sort(
        key=lambda p: p.get("time") or p.get("created_at") or p.get("ts") or 0,
        reverse=True,
    )
    if limit and limit > 0:
        posts = posts[:limit]
    return {"ok": True, "items": posts}


@router.post("/post")
def create_post(body: NewPost):
    """
    Create a new text or media post.
    """
    text = (body.text or "").strip()
    if not body.author or not text:
        raise HTTPException(status_code=400, detail="author and text are required")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="text is too long")

    p = {
        "author": body.author,
        "text": text,
        "tags": body.tags or [],
    }

    if body.media_url:
        p["media_url"] = body.media_url
    if body.content_type:
        p["content_type"] = body.content_type

    p = _append_post(p)
    return {"ok": True, "post": p}


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    visibility: str = Form("private"),
):
    """
    Upload a media file (video or image).

    If IPFS is available, we push the bytes there; otherwise this is a stub that
    returns a fake URL so the frontend doesn't crash.
    """
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"read_failed: {e}")

    # Basic size guard; main protection is WEALL_MAX_UPLOAD_BYTES in settings
    if not data:
        raise HTTPException(status_code=400, detail="empty_file")

    # Try IPFS if available
    cid = None
    url = None
    try:
        ipfs = getattr(executor, "ipfs", None)
        if ipfs is not None:
            res = ipfs.add_bytes(data)
            # res may be a dict or cid string depending on client
            if isinstance(res, dict):
                cid = res.get("Hash") or res.get("cid") or res.get("Cid")
            else:
                cid = str(res)
        if cid:
            url = f"ipfs://{cid}"
    except Exception:
        # use fallback URL if IPFS is offline
        cid = None

    if url is None:
        # Fallback: this endpoint is mostly for dev on your phone; we don't
        # persist the raw bytes here to avoid exhausting local storage.
        fake_id = str(uuid.uuid4())
        url = f"/dev/null/{fake_id}"

    return {"ok": True, "cid": cid, "url": url, "visibility": visibility}
