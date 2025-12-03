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

from dotenv import load_dotenv

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

from .settings import Settings
from .redirect_legacy_frontend import router as legacy_frontend_router
from .routers import auth_session_apply

from weall_node.weall_executor import executor
from weall_node.api import (
    ledger,
    wallet,
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
# App setup
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

settings = Settings()
WEALL_ENV = os.getenv("WEALL_ENV", "dev").lower()

_CORS_ORIGINS: List[str] = settings.CORS_ORIGINS
if WEALL_ENV in ("prod", "production") and any(
    (o or "").strip() == "*" for o in _CORS_ORIGINS
):
    raise RuntimeError("Wildcard CORS origins are not allowed when WEALL_ENV=prod")

app = FastAPI(title="WeAll Node API", version="1.1")

# Legacy redirect router for older /frontendtendtend/* paths
app.include_router(legacy_frontend_router)

# Auth (email proxy / apply-session bridge)
app.include_router(auth_session_apply.router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_headers=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)

# ------------------------------------------------------------
# Small shims for older frontends expecting /env.js + /api_shim.js
# ------------------------------------------------------------

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
    Serve the real file from weall_node/frontend/api_shim.js.
    """
    path = FRONTEND_DIR / "api_shim.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="api_shim.js not found")
    return FileResponse(path, media_type="application/javascript")


# ------------------------------------------------------------
# Common headers middleware (request ID + security headers)
# ------------------------------------------------------------

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
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self';",
    )
    return resp


# ------------------------------------------------------------
# Serve frontend static files
# ------------------------------------------------------------

frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")
else:
    print(f"[WARN] Frontend directory not found: {frontend_dir}")


# Root route – show login page (frontend handles redirect to feed if authed)
@app.get("/")
def root():
    login_path = Path(frontend_dir) / "login.html"
    if login_path.exists():
        return FileResponse(login_path)
    # Fallback: old location
    return RedirectResponse("/frontend/login.html", status_code=302)


# ------------------------------------------------------------
# Router mounts (modular API)
# ------------------------------------------------------------

app.include_router(ledger.router)
app.include_router(wallet.router)
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


# ------------------------------------------------------------
# Error boundary (wrap all handlers)
# ------------------------------------------------------------

@app.middleware("http")
async def error_boundary(request: Request, call_next):
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception as e:
        req_id = getattr(getattr(request, "state", None), "request_id", "-")
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": str(e),
                "request_id": req_id,
            },
        )


# ------------------------------------------------------------
# System meta
# ------------------------------------------------------------

@app.get("/version")
def version():
    return {"executor": "1.1", "api": app.version}



@app.get("/api/meta")
def api_meta():
    """
    Node metadata for top nav / diagnostics panel.
    Mirrors the shape expected by frontend/app.js:
      { ok: true, data: { node_id, roles, load, peers, env } }
    """
    # Derive node_id from executor or node_id.json
    node_id = getattr(executor, "node_id", None)
    if not node_id:
        try:
            import json
            nid_path = Path(settings.ROOT_DIR) / "node_id.json"
            if nid_path.exists():
                node_id = json.loads(nid_path.read_text()).get("node_id")
        except Exception:
            node_id = None
    if not node_id:
        node_id = "unknown"

    # Simple role model: operator vs observer + env-based role
    roles = []
    if WEALL_ENV != "observer":
        roles.append("operator")
    else:
        roles.append("observer")
    roles.append("dev" if WEALL_ENV != "prod" else "prod")

    # Basic node load metric: 1-minute system load or 0.0
    try:
        load_val = os.getloadavg()[0]
    except Exception:
        load_val = 0.0

    # Peer info from executor, if available
    peers = []
    try:
        peers = getattr(executor, "get_peer_list", lambda: [])() or []
    except Exception:
        peers = []

    return {
        "ok": True,
        "data": {
            "node_id": node_id,
            "roles": roles,
            "load": load_val,
            "peers": len(peers),
            "env": WEALL_ENV,
        },
    }


@app.post("/api/signup")
async def api_signup(payload: dict = Body(...)):
    """
    Email + password signup.

    - normalises email to an @handle account_id
    - derives a deterministic wallet (pubkey/address) from email+password
      using PBKDF2, without storing the raw password.
    - stores wallet metadata in executor.ledger["accounts"][account_id]
    """
    payload = payload or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="invalid_email")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="weak_password")

    account_id = "@" + email.split("@", 1)[0]

    try:
        wallet = derive_wallet_from_credentials(email, password, settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"wallet_derive_failed: {e}")

    # Persist minimal account record
    try:
        led = getattr(executor, "ledger", None)
        if led is not None:
            accounts = led.setdefault("accounts", {})
            acc = accounts.get(account_id) or {}
            acc.setdefault("email", email)
            acc["wallet"] = wallet
            accounts[account_id] = acc
            executor.save_state()
    except Exception:
        # Don't block signup if persistence fails in MVP
        pass

    return {
        "ok": True,
        "account_id": account_id,
        "wallet": wallet,
        "hint": "Now verify your email via /auth/start + /auth/verify.",
    }


@app.get("/api/v1/governance/proposals")
def api_v1_governance_proposals():
    """
    Back-compat alias for older frontends expecting /api/v1/governance/proposals.
    Delegates to the governance router's list_proposals().
    """
    try:
        return governance.list_proposals()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"governance_alias_failed: {e}")


def derive_wallet_from_credentials(email: str, password: str, settings: Settings) -> dict:
    """
    Derive a deterministic wallet (pubkey + address) from email+password
    using PBKDF2. This is MVP-only and assumes passwords have reasonable
    entropy for low/medium-value balances.
    """
    email_norm = (email or "").strip().lower()
    pwd = (password or "").strip()
    if not email_norm or not pwd:
        raise ValueError("email_and_password_required")

    identity = f"{email_norm}|{pwd}".encode("utf-8")
    node_salt_str = getattr(settings, "SECRET_KEY", None) or "weall-node-default-salt"
    node_salt = node_salt_str.encode("utf-8")

    seed = hashlib.pbkdf2_hmac("sha256", identity, node_salt, 200_000, dklen=32)

    if NACL_AVAILABLE and SigningKey is not None:
        sk = SigningKey(seed)
        vk = sk.verify_key
        pub_hex = vk.encode(encoder=HexEncoder).decode("ascii")
    else:
        # Fallback: still deterministic, just less nice crypto
        pub_hex = hashlib.sha256(seed).hexdigest()

    address = "we:" + pub_hex[:40]

    return {
        "kdf": "pbkdf2_sha256",
        "iterations": 200_000,
        "salt_hint": hashlib.sha256(node_salt).hexdigest()[:16],
        "pubkey": pub_hex,
        "address": address,
    }


# ------------------------------------------------------------
# EMAIL AUTH (MVP)
# ------------------------------------------------------------

# In-memory one-time codes
_AUTH_CODES = {}  # email -> { "code": str, "exp": float }


def _send_email_smtp(to_email: str, subject: str, body: str) -> bool:
    """
    Minimal SMTP helper; falls back to console logging if SMTP_* are unset.
    """
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
    _AUTH_CODES[email] = {"code": code, "exp": time.time() + 600}  # 10 minutes

    subject = "Your WeAll verification code"
    text = f"Your WeAll login code is: {code}\nThis code expires in 10 minutes."
    _send_email_smtp(email, subject, text)

    return {"ok": True, "ttl_sec": 600}




@app.post("/auth/send-code")
async def auth_send_code_alias(payload: dict = Body(...)):
    """
    Backwards-compatible alias for older frontends.
    Delegates to /auth/start.
    """
    return await auth_start(payload)

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
