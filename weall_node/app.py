#!/usr/bin/env python3
"""
WeAll FastAPI entrypoint (v0.5)
- Provides REST endpoints for user and content interaction.
- Delegates logic to the core WeAllExecutor runtime.
- Safe for local and production environments.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

# ✅ Fixed import path
from weall_node.weall_executor import WeAllExecutor

app = FastAPI(title="WeAll API", version="0.5.0")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to production frontend domain
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize executor
executor = WeAllExecutor(dsl_file="weall_dsl_v0.5.yaml")


# -------------------- Health Check --------------------
@app.get("/healthz")
def health_check():
    """Simple readiness probe for uptime monitoring."""
    return {"status": "ok", "ipfs_connected": bool(executor.ipfs)}


# -------------------- Users --------------------
@app.get("/users/{user_id}")
def get_user(user_id: str):
    """Return basic user profile, balance, and post list."""
    user = executor.state["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    posts = [pid for pid, p in executor.state["posts"].items() if p["user"] == user_id]
    balance = executor.ledger.balance(user_id)

    return {
        "user": user_id,
        "poh_level": user["poh_level"],
        "balance": balance,
        "posts": posts,
    }


# -------------------- Posts / Feed --------------------
def _safe_ipfs_cat(cid: str) -> str:
    """Safely fetch content from IPFS or return placeholder text."""
    if not executor.ipfs:
        return "[IPFS unavailable]"
    try:
        return executor.ipfs.cat(cid).decode()
    except Exception:
        return "[IPFS error]"


@app.get("/posts")
def get_posts():
    """Return all posts with latest first."""
    posts_list = []
    for pid, post in executor.state["posts"].items():
        posts_list.append(
            {
                "id": pid,
                "user": post["user"],
                "content": _safe_ipfs_cat(post["content_hash"]),
                "tags": post["tags"],
            }
        )
    posts_list.sort(key=lambda x: x["id"], reverse=True)
    return posts_list


# -------------------- Governance / Proposals --------------------
@app.get("/proposals")
def get_proposals():
    """List posts tagged under the Governance pallet."""
    proposals_list = []
    for pid, post in executor.state["posts"].items():
        if "Governance" in post.get("tags", []):
            proposals_list.append(
                {
                    "id": pid,
                    "user": post["user"],
                    "title": f"Proposal {pid}",
                    "description": _safe_ipfs_cat(post["content_hash"]),
                }
            )
    return proposals_list


# -------------------- Create Post --------------------
@app.post("/posts")
def create_post(
    user_id: str, content: str, tags: Optional[List[str]] = Query(default=None)
):
    """Create a new post and store it in IPFS."""
    if user_id not in executor.state["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    tags = tags or []
    result = executor.create_post(user_id, content, tags)
    if not result["ok"]:
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )
    return result


# -------------------- Create User --------------------
@app.post("/users")
def create_user(user_id: str, poh_level: int = 1):
    """Register a new user with a PoH level."""
    result = executor.register_user(user_id, poh_level)
    if not result["ok"]:
        raise HTTPException(
            status_code=400, detail=result.get("error", "Unknown error")
        )
    executor.set_user_eligible(user_id)
    return {"ok": True, "user": user_id}
