# weall_api.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from executor import WeAllExecutor, POH_REQUIREMENTS

app = FastAPI(title="WeAll Node API")
executor = WeAllExecutor(poh_requirements=POH_REQUIREMENTS)

# -----------------------------
# Request models
# -----------------------------
class UserModel(BaseModel):
    user_id: str
    poh_level: Optional[int] = 1

class PostModel(BaseModel):
    user_id: str
    content: str
    tags: Optional[List[str]] = None
    groups: Optional[List[str]] = None

class CommentModel(BaseModel):
    user_id: str
    post_id: int
    content: str
    tags: Optional[List[str]] = None

class ProposalModel(BaseModel):
    user_id: str
    title: str
    description: str
    pallet_reference: str

class VoteModel(BaseModel):
    user_id: str
    target_id: int
    vote_option: str

class DisputeModel(BaseModel):
    reporter_id: str
    target_post_id: int
    description: str

class JurorVoteModel(BaseModel):
    juror_id: str
    dispute_id: int
    vote_option: str

class MessageModel(BaseModel):
    from_user: str
    to_user: str
    message_text: str

# -----------------------------
# User endpoints
# -----------------------------
@app.post("/register")
def register_user(user: UserModel):
    return executor.register_user(user.user_id, user.poh_level)

@app.post("/add_friend")
def add_friend(user_id: str, friend_id: str):
    return executor.add_friend(user_id, friend_id)

@app.post("/create_group")
def create_group(user_id: str, group_name: str, members: Optional[List[str]] = None):
    return executor.create_group(user_id, group_name, members)

# -----------------------------
# Posts / Comments
# -----------------------------
@app.post("/post")
def create_post(post: PostModel):
    return executor.create_post(post.user_id, post.content, post.tags, post.groups)

@app.post("/comment")
def create_comment(comment: CommentModel):
    return executor.create_comment(comment.user_id, comment.post_id, comment.content, comment.tags)

@app.post("/edit_post")
def edit_post(user_id: str, post_id: int, new_content: str):
    return executor.edit_post(user_id, post_id, new_content)

@app.post("/delete_post")
def delete_post(user_id: str, post_id: int):
    return executor.delete_post(user_id, post_id)

@app.post("/edit_comment")
def edit_comment(user_id: str, comment_id: int, new_content: str):
    return executor.edit_comment(user_id, comment_id, new_content)

@app.post("/delete_comment")
def delete_comment(user_id: str, comment_id: int):
    return executor.delete_comment(user_id, comment_id)

@app.post("/like_post")
def like_post(user_id: str, post_id: int):
    return executor.like_post(user_id, post_id)

# -----------------------------
# Governance / Proposals
# -----------------------------
@app.post("/propose")
def propose(proposal: ProposalModel):
    return executor.propose(proposal.user_id, proposal.title, proposal.description, proposal.pallet_reference)

@app.post("/vote")
def vote(vote: VoteModel):
    return executor.vote(vote.user_id, vote.target_id, vote.vote_option)

# -----------------------------
# Disputes / Juror voting
# -----------------------------
@app.post("/create_dispute")
def create_dispute(dispute: DisputeModel):
    return executor.create_dispute(dispute.reporter_id, dispute.target_post_id, dispute.description)

@app.post("/juror_vote")
def juror_vote(vote: JurorVoteModel):
    return executor.juror_vote(vote.juror_id, vote.dispute_id, vote.vote_option)

@app.post("/report_post")
def report_post(reporter_id: str, post_id: int, description: str):
    return executor.report_post(reporter_id, post_id, description)

@app.post("/report_comment")
def report_comment(reporter_id: str, comment_id: int, description: str):
    return executor.report_comment(reporter_id, comment_id, description)

# -----------------------------
# Treasury
# -----------------------------
@app.post("/allocate_treasury")
def allocate_treasury(pool_name: str, amount: int):
    return executor.allocate_treasury(pool_name, amount)

@app.post("/reclaim_treasury")
def reclaim_treasury(pool_name: str, amount: int):
    return executor.reclaim_treasury(pool_name, amount)

# -----------------------------
# Messaging
# -----------------------------
@app.post("/send_message")
def send_message(msg: MessageModel):
    return executor.send_message(msg.from_user, msg.to_user, msg.message_text)

@app.get("/read_messages/{user_id}")
def read_messages(user_id: str):
    return executor.read_messages(user_id)

# -----------------------------
# Display posts / users
# -----------------------------
@app.get("/list_user_posts/{user_id}")
def list_user_posts(user_id: str):
    posts = [pid for pid, p in executor.state["posts"].items() if p["user"] == user_id]
    return {"posts": posts}

@app.get("/list_tag_posts/{tag}")
def list_tag_posts(tag: str):
    posts = [pid for pid, p in executor.state["posts"].items() if tag in p.get("tags", [])]
    return {"posts": posts}

@app.get("/show_post/{post_id}")
def show_post(post_id: int):
    post = executor.state["posts"].get(post_id)
    return post or {"error": "post_not_found"}

@app.get("/show_posts")
def show_posts():
    return executor.state["posts"]
