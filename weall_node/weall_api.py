# weall_api.py — FastAPI server for WeAll v1.1
# MPL-2.0

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from .executor import WeAllExecutor, POH_REQUIREMENTS

app = FastAPI(title="WeAll Node API", version="1.1")

# CORS (relaxed by default for MVP)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Single global executor for the process
EXEC = WeAllExecutor()

# -------------------- Models --------------------
class RegisterRequest(BaseModel):
    user_id: str
    poh_level: int = 1

class FriendRequest(BaseModel):
    user_id: str
    friend_id: str

class MessageRequest(BaseModel):
    from_user: str
    to_user: str
    text: str

class PostRequest(BaseModel):
    user_id: str
    content: str
    tags: Optional[List[str]] = None

class CommentRequest(BaseModel):
    user_id: str
    post_id: int
    content: str
    tags: Optional[List[str]] = None

class DisputeRequest(BaseModel):
    reporter_id: str
    target_type: str = Field(pattern="^(post|comment|profile)$")
    target_id: str
    reason: str

class MintPOHRequest(BaseModel):
    user_id: str
    tier: int

class TransferRequest(BaseModel):
    sender: str
    recipient: str
    amount: float

class TreasuryTransferRequest(BaseModel):
    recipient: str
    amount: float

class PoolSplitRequest(BaseModel):
    validators: float
    jurors: float
    creators: float
    storage: float
    treasury: float

# -------------------- Middleware --------------------
@app.middleware("http")
async def metrics_and_security(request: Request, call_next):
    # Minimal middleware; place for auth/rate-limits later
    try:
        response = await call_next(request)
        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Health & Metrics --------------------
@app.get("/health")
def health():
    return EXEC.get_health()

@app.get("/metrics")
def metrics():
    return EXEC.get_metrics()

@app.get("/version")
def version():
    return {"executor": "1.1", "api": app.version}

# -------------------- PoH / Config --------------------
@app.get("/poh/requirements")
def poh_requirements():
    return POH_REQUIREMENTS

@app.get("/poh/status/{user_id}")
def poh_status(user_id: str):
    u = EXEC.state["users"].get(user_id)
    if not u:
        raise HTTPException(404, "user_not_found")
    return {"user_id": user_id, "poh_level": u.get("poh_level", 0), "nfts": u.get("nfts", [])}

# -------------------- Users & Friends --------------------
@app.post("/register")
def register(req: RegisterRequest):
    return EXEC.register_user(req.user_id, poh_level=req.poh_level)

@app.post("/friend")
def add_friend(req: FriendRequest):
    return EXEC.add_friend(req.user_id, req.friend_id)

@app.post("/message")
def send_message(req: MessageRequest):
    return EXEC.send_message(req.from_user, req.to_user, req.text)

@app.get("/messages/{user_id}")
def read_messages(user_id: str):
    return EXEC.read_messages(user_id)

# -------------------- Content --------------------
@app.post("/post")
def create_post(req: PostRequest):
    return EXEC.create_post(req.user_id, req.content, req.tags or [])

@app.post("/comment")
def create_comment(req: CommentRequest):
    return EXEC.create_comment(req.user_id, req.post_id, req.content, req.tags or [])

@app.get("/show_posts")
def show_posts():
    return {"ok": True, "posts": EXEC.state["posts"]}

# -------------------- Disputes --------------------
@app.post("/dispute")
def create_dispute(req: DisputeRequest):
    target_id = int(req.target_id) if req.target_type in ("post", "comment") and req.target_id.isdigit() else req.target_id
    return EXEC.create_dispute(req.reporter_id, req.target_type, target_id, req.reason)

# -------------------- NFTs --------------------
@app.post("/mint_poh")
def mint_poh(req: MintPOHRequest):
    return EXEC.mint_poh_nft(req.user_id, req.tier)

# -------------------- Ledger --------------------
@app.get("/ledger/balance/{user_id}")
def balance(user_id: str):
    return {"ok": True, "user_id": user_id, "balance": EXEC.ledger.balance(user_id)}

@app.post("/ledger/transfer")
def transfer(req: TransferRequest):
    return EXEC.transfer(req.sender, req.recipient, req.amount)

@app.post("/ledger/treasury/transfer")
def treasury_transfer(req: TreasuryTransferRequest):
    return EXEC.treasury_transfer(req.recipient, req.amount)

# -------------------- Governance (basic views) --------------------
@app.get("/governance/status")
def governance_status():
    active = getattr(EXEC, "governance", None) is not None
    count = len(getattr(getattr(EXEC, "governance", None), "proposals", [])) if active else 0
    return {"active": active, "proposals": count}

@app.get("/governance/proposals")
def governance_list():
    if not getattr(EXEC, "governance", None):
        return {"ok": False, "error": "governance_unavailable"}
    return {"ok": True, "items": getattr(EXEC.governance, "proposals", [])}

# -------------------- Config / Admin --------------------
@app.post("/admin/pool_split")
def set_pool_split(req: PoolSplitRequest):
    split = req.dict()
    if abs(sum(split.values()) - 1.0) > 1e-6:
        raise HTTPException(400, "split_must_sum_to_1")
    EXEC.set_pool_split(split)
    return {"ok": True, "pool_split": EXEC.pool_split}

@app.post("/admin/blocks_per_epoch/{bpe}")
def set_blocks_per_epoch(bpe: int):
    EXEC.set_blocks_per_epoch(bpe)
    return {"ok": True, "blocks_per_epoch": EXEC.blocks_per_epoch}

@app.post("/admin/halving_interval/{epochs}")
def set_halving_interval(epochs: int):
    EXEC.set_halving_interval_epochs(epochs)
    return {"ok": True, "halving_interval_epochs": EXEC.halving_interval_epochs}

@app.post("/admin/save")
def admin_save():
    return EXEC.save_state()

@app.post("/admin/load")
def admin_load():
    return EXEC.load_state()

# -------------------- P2P --------------------
@app.get("/p2p/peers")
def p2p_peers():
    return {"node_id": EXEC.node_id, "peers": EXEC.p2p.get_peer_list()}

@app.post("/p2p/add_peer/{peer_id}")
def p2p_add_peer(peer_id: str):
    EXEC.p2p.add_peer(peer_id)
    return {"ok": True, "peers": EXEC.p2p.get_peer_list()}

# -------------------- Blocks --------------------
@app.post("/block/new/{producer_id}")
def new_block(producer_id: str):
    return EXEC.on_new_block(producer_id)

@app.post("/block/sim/{n}")
def simulate(n: int):
    EXEC.simulate_blocks(n)
    return {"ok": True, "height": EXEC.current_block_height}
