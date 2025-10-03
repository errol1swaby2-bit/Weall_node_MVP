from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from executor import WeAllExecutor
from typing import List

app = FastAPI(title="WeAll API")

# Enable CORS so frontend (localhost) can call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict to frontend domain later
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize executor
executor = WeAllExecutor(dsl_file="weall_dsl_v0.5.yaml")

# -------------------- Users --------------------
@app.get("/users/{user_id}")
def get_user(user_id: str):
    user = executor.state["users"].get(user_id)
    if not user:
        return {"error": "User not found"}

    # Gather user posts
    posts = [pid for pid, p in executor.state["posts"].items() if p["user"] == user_id]
    balance = executor.ledger.balance(user_id)

    return {
        "user": user_id,
        "poh_level": user["poh_level"],
        "balance": balance,
        "posts": posts,
    }

# -------------------- Posts / Feed --------------------
@app.get("/posts")
def get_posts():
    posts_list = []
    for pid, post in executor.state["posts"].items():
        # For simplicity, retrieve content from IPFS if available
        try:
            content = executor.ipfs.cat(post["content_hash"]).decode() if executor.ipfs else "[IPFS unavailable]"
        except Exception:
            content = "[IPFS error]"
        posts_list.append({
            "id": pid,
            "user": post["user"],
            "content": content,
            "tags": post["tags"]
        })
    # Return newest posts first
    posts_list.sort(key=lambda x: x["id"], reverse=True)
    return posts_list

# -------------------- Governance / Proposals --------------------
@app.get("/proposals")
def get_proposals():
    proposals_list = []
    for pid, post in executor.state["posts"].items():
        # Treat posts in "Governance" pallet as proposals
        if "Governance" in post.get("tags", []):
            try:
                content = executor.ipfs.cat(post["content_hash"]).decode() if executor.ipfs else "[IPFS unavailable]"
            except Exception:
                content = "[IPFS error]"
            proposals_list.append({
                "id": pid,
                "user": post["user"],
                "title": f"Proposal {pid}",
                "description": content
            })
    return proposals_list

# -------------------- Create Post --------------------
@app.post("/posts")
def create_post(user_id: str, content: str, tags: List[str] = []):
    if user_id not in executor.state["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    result = executor.create_post(user_id, content, tags)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    return result

# -------------------- Create User --------------------
@app.post("/users")
def create_user(user_id: str, poh_level: int = 1):
    result = executor.register_user(user_id, poh_level)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    executor.set_user_eligible(user_id)
    return {"ok": True, "user": user_id}
