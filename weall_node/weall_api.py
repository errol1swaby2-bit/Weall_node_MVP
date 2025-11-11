"""
WeAll Node — Unified FastAPI Interface
--------------------------------------
• Serves frontend HTML/JS under /frontendtendtend/
• Exposes all backend API modules
• Provides all routes called by the web client
• Production hardening: CORS, request IDs, security headers
"""

import os
import uuid
from dotenv import load_dotenv
from typing import List, Optional

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .redirect_legacy_frontend import router as legacy_frontend_router
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse

try:
    # removed fastapi_mail
    MAILER_AVAILABLE = True
except Exception:
    MAILER_AVAILABLE = False

from pydantic import BaseModel, Field

from weall_node.weall_executor import WeAllExecutor
from weall_node.api import (
    ledger,
    pinning,
    governance,
    sync,
    messaging,
    poh,
    treasury,
    verification,
    disputes,
    content,
    reputation,
    chain,
    validators,
    operators,
    rewards,
    storage,
    health,
    feed,
    recovery,
)

# ------------------------------------------------------------
# App Setup
# ------------------------------------------------------------
_CORS_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]

from fastapi import Body

app = FastAPI(title="WeAll Node API", version="1.1")
app.include_router(legacy_frontend_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)

# --- Mailer config (reads from .env) ---
MAIL_CONF = ()
mailer = (MAIL_CONF) if MAILER_AVAILABLE else None


# Combined middleware: assigns a request ID and adds security headers
@app.middleware("http")
async def common_headers(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = req_id
    resp = await call_next(request)
    resp.headers["X-Request-ID"] = req_id
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), interest-cohort=()",
    )
    # Conservative CSP for the static frontend; adjust if you add external CDNs
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self';",
    )
    return resp


# ------------------------------------------------------------
# Serve Frontend Static Files
# ------------------------------------------------------------
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")
else:
    print(f"[WARN] Frontend directory not found: {frontend_dir}")


# Default route → dashboard
@app.get("/")
def root():
    # Serve login.html directly (HTTP 200) to avoid loops
    try:
        from pathlib import Path
        return FileResponse(Path(frontend_dir)/"login.html")
    except Exception:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/frontend/login.html", status_code=302)


# ------------------------------------------------------------
# Router Mounts (API Modules)
# ------------------------------------------------------------
app.include_router(ledger.router)
app.include_router(pinning.router)
app.include_router(governance.router)
app.include_router(sync.router)
app.include_router(messaging.router)
app.include_router(poh.router)
app.include_router(treasury.router)
app.include_router(verification.router)
app.include_router(disputes.router)
app.include_router(content.router)
app.include_router(reputation.router)
app.include_router(chain.router)
app.include_router(validators.router)
app.include_router(operators.router)
app.include_router(rewards.router)
app.include_router(storage.router)
app.include_router(health.router)
app.include_router(feed.router)
app.include_router(recovery.router)


import smtplib, ssl


def _send_email_smtp(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "465") or 465)
    user = os.getenv("SMTP_USER", "")
    pwd = os.getenv("SMTP_PASS", "")
    from_addr = os.getenv("MAIL_FROM", "WeAll <no-reply@weall.local>")
    use_ssl = os.getenv("MAIL_SSL", "1") == "1"
    use_tls = os.getenv("MAIL_TLS", "0") == "1"
    if not host or not port:
        print(f"[MAIL:FALLBACK] {to_email} <- {subject}\n{body}")
        return False
    msg = f"From: {from_addr}\r\nTo: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                if user:
                    s.login(user, pwd)
                s.sendmail(from_addr, [to_email], msg.encode("utf-8"))
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, pwd)
                s.sendmail(from_addr, [to_email], msg.encode("utf-8"))
        print(f"[MAIL] sent to {to_email}")
        return True
    except Exception as e:
        print(f"[MAIL] send failed to {to_email}: {e}")
        print(f"[MAIL:FALLBACK] {to_email} <- {subject}\n{body}")
        return False


# ------------------------------------------------------------
# Executor Runtime
# ------------------------------------------------------------
EXEC = WeAllExecutor()


# ------------------------------------------------------------
# Request Models (legacy endpoints below use these)
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# Basic error boundary around handlers
# ------------------------------------------------------------
@app.middleware("http")
async def error_boundary(request: Request, call_next):
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception as e:
        # Surface request id for easier debugging
        req_id = getattr(getattr(request, "state", None), "request_id", "-")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": str(e), "request_id": req_id},
        )


# ------------------------------------------------------------
# System Health / Meta
# ------------------------------------------------------------
@app.get("/version")
def version():
    return {"executor": "1.1", "api": app.version}


# ------------------------------------------------------------
# Proof of Humanity (Frontend Hooks)
# ------------------------------------------------------------
@app.get("/poh/status/{user_id}")
def poh_status(user_id: str):
    u = EXEC.state["users"].get(user_id)
    if not u:
        raise HTTPException(404, "user_not_found")
    return {
        "user_id": user_id,
        "poh_level": u.get("poh_level", 0),
        "nfts": u.get("nfts", []),
    }


# ------------------------------------------------------------
# User / Messaging
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# Posts / Comments
# ------------------------------------------------------------
@app.post("/post")
def create_post(req: PostRequest):
    return EXEC.create_post(req.user_id, req.content, req.tags or [])


@app.post("/comment")
def create_comment(req: CommentRequest):
    return EXEC.create_comment(req.user_id, req.post_id, req.content, req.tags or [])


@app.get("/show_posts")
def show_posts():
    return {"ok": True, "posts": EXEC.state.get("posts", {})}


# ------------------------------------------------------------
# Governance (legacy helpers)
# ------------------------------------------------------------
@app.get("/governance/proposals")
def governance_list():
    gov = getattr(EXEC, "governance", None)
    if not gov:
        return {"ok": False, "error": "governance_unavailable"}
    proposals = getattr(gov, "proposals", [])
    return {str(i): p for i, p in enumerate(proposals)}


@app.post("/governance/vote")
def governance_vote(data: dict):
    user = data.get("user")
    pid = data.get("proposal_id")
    vote = data.get("vote")
    return EXEC.cast_vote(user, pid, vote)


@app.post("/governance/new")
def governance_new(data: dict):
    title = data.get("title")
    desc = data.get("description")
    amount = data.get("amount")
    return EXEC.create_proposal(title, desc, amount)


# ------------------------------------------------------------
# Ledger / Treasury
# ------------------------------------------------------------
@app.get("/ledger/balance/{user_id}")
def balance(user_id: str):
    return {"ok": True, "user_id": user_id, "balance": EXEC.ledger.balance(user_id)}


@app.post("/ledger/transfer")
def transfer(req: TransferRequest):
    return EXEC.transfer(req.sender, req.recipient, req.amount)


@app.post("/ledger/treasury/transfer")
def treasury_transfer(req: TreasuryTransferRequest):
    return EXEC.treasury_transfer(req.recipient, req.amount)


# ------------------------------------------------------------
# Disputes
# ------------------------------------------------------------
@app.post("/dispute")
def create_dispute(req: DisputeRequest):
    target_id = (
        int(req.target_id)
        if req.target_type in ("post", "comment") and str(req.target_id).isdigit()
        else req.target_id
    )
    return EXEC.create_dispute(req.reporter_id, req.target_type, target_id, req.reason)


# ------------------------------------------------------------
# NFTs (PoH & custom)
# ------------------------------------------------------------
@app.post("/mint_poh")
def mint_poh(req: MintPOHRequest):
    return EXEC.mint_poh_nft(req.user_id, req.tier)


# ------------------------------------------------------------
# P2P / Blocks
# ------------------------------------------------------------
@app.get("/p2p/peers")
def p2p_peers():
    return {"node_id": EXEC.node_id, "peers": EXEC.p2p.get_peer_list()}


@app.post("/p2p/add_peer/{peer_id}")
def p2p_add_peer(peer_id: str):
    EXEC.p2p.add_peer(peer_id)
    return {"ok": True, "peers": EXEC.p2p.get_peer_list()}


@app.post("/block/new/{producer_id}")
def new_block(producer_id: str):
    return EXEC.on_new_block(producer_id)


@app.post("/block/sim/{n}")
def simulate_blocks(n: int):
    EXEC.simulate_blocks(n)
    return {"ok": True, "height": EXEC.current_block_height}


# ------------------------------------------------------------
# Admin Config
# ------------------------------------------------------------
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


# --- safety redirects for legacy root paths ---
from fastapi.responses import RedirectResponse, FileResponse


@app.get("/login.html")
def _redir_login():
    return RedirectResponse(url="/frontendtendtend/login.html", status_code=307)


@app.get("/signup.html")
def _redir_signup():
    return RedirectResponse(url="/frontendtendtend/onboarding.html", status_code=307)


@app.get("/index.html")
def _redir_index():
    return RedirectResponse(url="/frontendtendtend/index.html", status_code=307)


# --- end safety redirects ---


# --- Back-compat auth aliases (old frontend) ---
@app.post("/auth/email/request_code")
async def alias_request_code(payload: dict = Body(...)):
    # expect {"email": "..."}
    return await auth_start(payload)


@app.post("/auth/email/verify_code")
async def alias_verify_code(payload: dict = Body(...)):
    # expect {"email":"...", "code":"123456"}
    return await auth_verify(payload)


# --- Back-compat: alias legacy auth paths to new handlers ---
try:
    # Reuse the exact same callables so validation/deps stay identical
    app.add_api_route("/auth/email/request_code", auth_start, methods=["POST"])
    app.add_api_route("/auth/email/verify_code", auth_verify, methods=["POST"])
except NameError:
    # If definitions are above but names differ, fail silently; we'll see 404 and fix by name.
    pass


# === === ===  EMAIL AUTH (MVP)  === === ===
# ### >>> EMAIL AUTH (MVP) <<<  — dev-only, logs code to console.
from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
import os, secrets, time, ssl, smtplib

# In-memory one-time codes
_AUTH_CODES = {}  # email -> { "code":str, "exp":float }


# --- SMTP helper (stdlib; reads env). Falls back to console if SMTP_* unset.
def _send_email_smtp(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "465") or 465)
    user = os.getenv("SMTP_USER", "")
    pwd = os.getenv("SMTP_PASS", "")
    from_addr = os.getenv("MAIL_FROM", "WeAll <no-reply@weall.local>")
    use_ssl = os.getenv("MAIL_SSL", "1") == "1"
    use_tls = os.getenv("MAIL_TLS", "0") == "1"

    if not host or not port:
        print(f"[MAIL:FALLBACK] {to_email} <- {subject}\n{body}")
        return False

    msg = f"From: {from_addr}\r\nTo: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                if user:
                    s.login(user, pwd)
                s.sendmail(from_addr, [to_email], msg.encode("utf-8"))
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, pwd)
                s.sendmail(from_addr, [to_email], msg.encode("utf-8"))
        print(f"[MAIL] sent to {to_email}")
        return True
    except Exception as e:
        print(f"[MAIL] send failed to {to_email}: {e}")
        print(f"[MAIL:FALLBACK] {to_email} <- {subject}\n{body}")
        return False


@app.post("/auth/start")
async def auth_start(payload: dict = Body(...)):
    email = (payload or {}).get("email", "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="invalid_email")

    code = f"{secrets.randbelow(10**6):06d}"
    _AUTH_CODES[email] = {"code": code, "exp": time.time() + 600}  # 10 min

    subject = "Your WeAll verification code"
    text = f"Your WeAll login code is: {code}\nThis code expires in 10 minutes."
    _send_email_smtp(email, subject, text)

    return {"ok": True, "ttl_sec": 600}


@app.post("/auth/verify")
async def auth_verify(payload: dict = Body(...)):
    email = (payload or {}).get("email", "").strip().lower()
    code = (payload or {}).get("code", "").strip()
    rec = _AUTH_CODES.get(email)
    if not rec:
        raise HTTPException(status_code=404, detail="no_code")
    if time.time() > rec["exp"]:
        _AUTH_CODES.pop(email, None)
        raise HTTPException(status_code=400, detail="expired")
    if code != rec["code"]:
        raise HTTPException(status_code=400, detail="bad_code")

    _AUTH_CODES.pop(email, None)
    acct = "@" + email.split("@")[0]  # simple dev ID
    resp = JSONResponse({"ok": True, "account_id": acct, "nft_minted": False})
    resp.set_cookie("weall_session", f"dev::{acct}", httponly=False, samesite="Lax")
    return resp


# Legacy aliases for old frontend
try:
    app.add_api_route("/auth/email/request_code", auth_start, methods=["POST"])
    app.add_api_route("/auth/email/verify_code", auth_verify, methods=["POST"])
except Exception:
    pass
# ### <<< EMAIL AUTH (MVP) <<<

# --- WeAll Genesis: mount reputation API ------------------------------------
# Non-invasive: if this module defines `app` (or a create_app pattern uses it),
# attach the /reputation endpoints.

try:
    from weall_node.api import reputation as _reputation_api  # type: ignore
except Exception:
    _reputation_api = None  # type: ignore[assignment]

_app = globals().get("app")

if _app is not None and _reputation_api is not None:
    try:
        _app.include_router(_reputation_api.router)
    except Exception:
        # If routing is structured differently or already mounted, fail silently.
        pass
