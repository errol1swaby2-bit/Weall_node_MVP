# api/content.py
from fastapi import APIRouter

router = APIRouter(prefix="/content", tags=["Content"])

posts = {}
comments = {}
post_counter = 1
comment_counter = 1

@router.post("/create_post")
def create_post(user_id: str, content: str):
    global post_counter
    pid = post_counter
    posts[pid] = {"user": user_id, "content": content, "comments": []}
    post_counter += 1
    return {"ok": True, "post_id": pid}

@router.post("/comment")
def comment(user_id: str, post_id: int, content: str):
    global comment_counter
    if post_id not in posts:
        return {"ok": False, "error": "post_not_found"}
    cid = comment_counter
    comments[cid] = {"user": user_id, "content": content, "post_id": post_id}
    posts[post_id]["comments"].append(cid)
    comment_counter += 1
    return {"ok": True, "comment_id": cid}
