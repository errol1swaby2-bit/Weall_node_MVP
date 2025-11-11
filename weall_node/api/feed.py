"""
weall_node/api/feed.py
--------------------------------------------------
Decentralized content feed API.
Allows users to post content (pinned to IPFS),
view trending or personalized feeds, and react to posts.

Dependencies:
- executor: handles ledger state, rewards, and persistence
- IPFSManager: handles pinning
- ledger: persists post and reaction records
"""

import time, random, hashlib
from typing import List, Dict, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

from ..weall_executor import executor

router = APIRouter(prefix="/feed", tags=["Feed"])


# -----------------------------------------------------------
# Data Models
# -----------------------------------------------------------
class ContentPost(BaseModel):
    user_id: str
    title: str
    description: Optional[str] = None
    cid: Optional[str] = None


class Reaction(BaseModel):
    user_id: str
    target_cid: str
    reaction: str  # e.g. 'like', 'love', 'dislike', 'share', 'comment'


# -----------------------------------------------------------
# Core logic
# -----------------------------------------------------------
def _score_post(post: Dict[str, any]) -> float:
    """Simple time-decay + engagement scoring."""
    age_hours = (time.time() - post["timestamp"]) / 3600
    base_score = post.get("engagement", 0) * 2.0 + post.get("reactions", 0) * 1.0
    decay = max(0.2, 1.0 / (1.0 + age_hours / 24))
    return base_score * decay


# -----------------------------------------------------------
# Routes
# -----------------------------------------------------------
@router.post("/content")
async def post_content(
    user_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    """User uploads content and pins to IPFS."""
    ipfs = getattr(executor, "ipfs", None)
    if not ipfs:
        raise HTTPException(status_code=503, detail="IPFS not available")

    # Pin file or fallback to text-only
    if file:
        res = ipfs.add_bytes(await file.read())
        cid = res["Hash"]
    else:
        # Create pseudo-CID for text posts
        cid = hashlib.sha1(f"{user_id}:{title}:{time.time()}".encode()).hexdigest()

    # Record in ledger / executor
    entry = {
        "cid": cid,
        "user": user_id,
        "title": title,
        "description": description,
        "timestamp": int(time.time()),
        "reactions": 0,
        "engagement": 0.0,
    }

    executor.ledger.setdefault("content", []).append(entry)
    executor.save_state()

    return {"ok": True, "cid": cid, "message": "Content posted successfully."}


@router.post("/react")
def react(req: Reaction):
    """User reacts to a piece of content."""
    posts = executor.ledger.get("content", [])
    post = next((p for p in posts if p["cid"] == req.target_cid), None)
    if not post:
        raise HTTPException(status_code=404, detail="Content not found")

    post["reactions"] = post.get("reactions", 0) + 1
    if req.reaction in ("like", "love"):
        post["engagement"] = post.get("engagement", 0.0) + 1.0
    elif req.reaction == "dislike":
        post["engagement"] = max(0.0, post.get("engagement", 0.0) - 0.5)

    executor.save_state()
    return {"ok": True, "cid": req.target_cid, "new_score": _score_post(post)}


@router.get("/feed")
def get_feed(limit: int = 20) -> Dict[str, List[dict]]:
    """Return personalized feed (simple random for now)."""
    posts = executor.ledger.get("content", [])
    if not posts:
        return {"ok": True, "feed": []}

    ranked = sorted(posts, key=_score_post, reverse=True)
    return {"ok": True, "feed": ranked[:limit]}


@router.get("/trending")
def get_trending(limit: int = 10) -> Dict[str, List[dict]]:
    """Return globally trending content (high score + recent)."""
    posts = executor.ledger.get("content", [])
    ranked = sorted(posts, key=_score_post, reverse=True)
    return {"ok": True, "trending": ranked[:limit]}
