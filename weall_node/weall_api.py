# weall_node/weall_api.py
"""
WeAll Node — Unified FastAPI Interface
--------------------------------------
• Serves frontend HTML/JS under /frontend
• Exposes all backend API modules
• Provides all routes called by the web client
• Production hardening: CORS, request IDs, security headers
"""
import os
import uuid
import secrets
import time
import ssl
import smtplib
import hashlib, binascii
from pathlib import Path
from typing import List, Optional
from .api import roles
from dotenv import load_dotenv
from .api import disputes as disputes_api

load_dotenv()

try:
    from nacl.signing import SigningKey  # type: ignore
    from nacl.encoding import HexEncoder  # type: ignore
    NACL_AVAILABLE = True
except Exception:
    SigningKey = None  # type: ignore
    HexEncoder = None  # type: ignore
    NACL_AVAILABLE = False

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field
from .api.wallet import wallet_router, faucet_router
from .settings import Settings
from .redirect_legacy_frontend import router as legacy_frontend_router
from .routers import auth_session_apply

from weall_node.weall_executor import executor

from .api import (  # noqa: E402
    poh,
    governance,
    treasury,
    rewards,
    storage,
    health as health_router,
    content,
    sync,
    ledger,
    reputation,
    messaging,
    disputes,
    pinning,
    verification,
    chain,
    compat,
    validators,
    operators,
    consensus,
    recovery,
    faucet,
    p2p_overlay,
    roles,
    groups)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"


# ---------------------------------------------------------------------------
# Settings and app init
# ---------------------------------------------------------------------------


settings = Settings()

app = FastAPI(
    title="WeAll Node API",
    description="Unified WeAll Node backend (auth, content, governance, chain, p2p).",
    version="1.1.0",
)


# ---------------------------------------------------------------------------
# CORS and middleware
# ---------------------------------------------------------------------------


# Allow local dev + simple mobile debugging; can be tightened later.
origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://0.0.0.0:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id_and_security_headers(request: Request, call_next):
    """
    Attach a simple request ID and some basic security headers to all responses.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    return response


# ---------------------------------------------------------------------------
# Frontend static files and SPA routing
# ---------------------------------------------------------------------------


# Mount /frontend static files
app.mount(
    "/frontend",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)


# Legacy redirect handler for older entrypoints (index.html → /frontend/index.html)
app.include_router(legacy_frontend_router)


@app.get("/")
async def root_to_frontend():
    """
    Redirect bare / to the TikTok-style frontend for now.
    """
    return RedirectResponse(url="/frontend/index.html")


@app.get("/env.js")
async def serve_env_js():
    """
    Compatibility shim: some frontend entrypoints request /env.js at the root.
    Serve the real file from weall_node/frontend/env.js.
    """
    path = FRONTEND_DIR / "env.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="env.js not found")
    return FileResponse(path, media_type="application/javascript")


@app.get("/api_shim.js")
async def serve_api_shim_js():
    """
    Compatibility shim: some frontend entrypoints request /api_shim.js at the root.
    This file wires window.API_BASE etc. for the SPA.
    """
    path = FRONTEND_DIR / "api_shim.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="api_shim.js not found")
    return FileResponse(path, media_type="application/javascript")


# ---------------------------------------------------------------------------
# Include API routers
# ---------------------------------------------------------------------------

app.include_router(auth_session_apply.router, prefix="/auth")

# Core protocol / governance
app.include_router(poh.router)
app.include_router(governance.router)
app.include_router(treasury.router)
app.include_router(rewards.router)
app.include_router(reputation.router, prefix="/reputation")
app.include_router(validators.router)
app.include_router(operators.router)
app.include_router(consensus.router)
app.include_router(recovery.router)
app.include_router(faucet_router)
app.include_router(wallet_router)
app.include_router(roles.router, prefix="/roles", tags=["roles"])
app.include_router(disputes_api.router)
app.include_router(groups.router)

# Messaging / sync / ledger / storage
app.include_router(messaging.router)    # /messaging/... + legacy /content alias
app.include_router(sync.router)         # sync / p2p wiring
app.include_router(ledger.router)       # ledger inspection endpoints
app.include_router(storage.router)      # /storage/... (IPFS / local)
app.include_router(p2p_overlay.router)  # /p2p/... identity & peers

# Content / disputes / pinning / verification
app.include_router(content.router)
app.include_router(disputes.router)
app.include_router(pinning.router)
app.include_router(verification.router)

# Chain / compatibility / health
app.include_router(chain.router)
app.include_router(compat.router)
app.include_router(health_router.router, prefix="/api/health")


# ---------------------------------------------------------------------------
# Node / meta info
# ---------------------------------------------------------------------------


class MetaResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)


@app.get("/api/meta", response_model=MetaResponse)
async def api_meta():
    """
    Lightweight node metadata for the frontend:

        {
          "ok": true,
          "data": {
            "node_id": "...",
            "roles": ["validator", "operator"],
            "load": 0.12,
            "peers": 3
          }
        }
    """
    # Executor node id and roles
    node_id = getattr(executor, "node_id", None) or "node:unknown"
    roles: List[str] = []

    try:
        if getattr(executor, "validator_enabled", False):
            roles.append("validator")
    except Exception:
        pass

    try:
        if getattr(executor, "operator_enabled", False):
            roles.append("operator")
    except Exception:
        pass

    # Basic node load metric: 1-minute system load or 0.0
    try:
        load_val = os.getloadavg()[0]
    except Exception:
        load_val = 0.0

    # Peer info from executor.p2p, if available
    peers = []
    try:
        p2p = getattr(executor, "p2p", None)
        if p2p is not None:
            get_peer_list = getattr(p2p, "get_peer_list", None)
            if callable(get_peer_list):
                peers = get_peer_list() or []
    except Exception:
        peers = []

    return {
        "ok": True,
        "data": {
            "node_id": node_id,
            "roles": roles,
            "load": load_val,
            "peers": len(peers),
        },
    }


# ---------------------------------------------------------------------------
# Minimal auth email code path (dev-friendly)
# ---------------------------------------------------------------------------

# NOTE: This is intentionally simple and not production-hardened. For Genesis,
# email "verification" is purely for convenience and developer testing.


class AuthEmailRequest(BaseModel):
    email: str = Field(..., max_length=320)


class AuthEmailVerify(BaseModel):
    email: str = Field(..., max_length=320)
    code: str = Field(..., max_length=6)


_AUTH_CODES: dict = {}
_AUTH_CODES_EXPIRY: dict = {}


def _send_email_smtp(to_email: str, subject: str, body: str) -> None:
    """
    Very minimal SMTP client for sending auth codes.
    Reads SMTP settings from environment variables:

        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TLS

    In dev environments where these are not set, this becomes a no-op and just logs.
    """
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM") or user

    if not host or not sender:
        print(f"[AUTH EMAIL] Would send to {to_email}: {subject} — {body}")
        return

    use_tls = os.getenv("SMTP_TLS", "true").lower() in ("1", "true", "yes")
    try:
        if use_tls:
            context = ssl.create_default_context()
            server = smtplib.SMTP(host, port)
            server.starttls(context=context)
        else:
            server = smtplib.SMTP(host, port)

        if user and password:
            server.login(user, password)

        msg = f"From: {sender}\r\nTo: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
        server.sendmail(sender, [to_email], msg)
        server.quit()
    except Exception as exc:
        print(f"[AUTH EMAIL] Failed to send email: {exc}")


@app.post("/auth/send-code")
async def auth_start(payload: AuthEmailRequest):
    """
    Start email-based dev auth: generate a 6-digit code and send it via email.
    """
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="invalid_email")

    # Simple 6-digit code
    code = f"{secrets.randbelow(1_000_000):06d}"
    _AUTH_CODES[email] = code
    _AUTH_CODES_EXPIRY[email] = time.time() + 15 * 60  # 15 minutes

    _send_email_smtp(
        to_email=email,
        subject="Your WeAll verification code",
        body=f"Your verification code is: {code}",
    )

    return {"ok": True}


@app.post("/auth/verify")
async def auth_verify(payload: AuthEmailVerify):
    """
    Complete email-based dev auth: verify the code and return a fake session cookie.
    """
    email = payload.email.strip().lower()
    code = payload.code.strip()

    expected = _AUTH_CODES.get(email)
    expiry = _AUTH_CODES_EXPIRY.get(email, 0)

    if not expected or expected != code or time.time() > expiry:
        raise HTTPException(status_code=400, detail="invalid_code")

    # Clear code and issue a simple dev session id
    _AUTH_CODES.pop(email, None)
    _AUTH_CODES_EXPIRY.pop(email, None)

    acct = "@" + email.split("@")[0]
    resp = JSONResponse({"ok": True, "account_id": acct, "nft_minted": False})
    resp.set_cookie("weall_session", f"dev::{acct}", httponly=False, samesite="Lax")
    return resp


# Legacy aliases for the old frontend
try:
    app.add_api_route("/auth/email/request_code", auth_start, methods=["POST"])
    app.add_api_route("/auth/email/verify_code", auth_verify, methods=["POST"])
except Exception:
    pass
