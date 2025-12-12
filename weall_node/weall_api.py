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
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Dict

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .settings import Settings
from .redirect_legacy_frontend import router as legacy_frontend_router
from .routers import auth_session_apply
from .security import auth_db
from .api.wallet import wallet_router, faucet_router

from weall_node.weall_executor import executor

from .api import roles
from .api import disputes as disputes_api
from .api import (  # noqa: E402
    poh,
    governance,
    treasury,
    rewards,
    storage,
    health as health_router,
    health_ready,
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
    groups,
    node_meta,
    ops_ledger,
)


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

settings = Settings()

app = FastAPI(
    title="WeAll Node API",
    description="Unified WeAll Node backend (auth, content, governance, chain, p2p).",
    version="1.1.0",
)

# ------------------------------------------------------------
@app.on_event("startup")
async def _init_auth_db() -> None:
    # Stable session storage: SQLite in DATA_DIR
    from pathlib import Path as _Path
    db_path = str(_Path(settings.DATA_DIR) / "weall_auth.db")
    auth_db.init(db_path)
    auth_db.purge_expired_sessions()

# CORS
# ------------------------------------------------------------

origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "capacitor://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# Middleware (fixed for FastAPI)
# ------------------------------------------------------------

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """
    Attach X-Request-ID to incoming requests and responses for easier tracing.
    """
    req_id = uuid.uuid4().hex[:16]
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


@app.middleware("http")
async def no_store_frontend(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path or ""
    if path.startswith("/frontend/") or path == "/env.js":
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """
    Attach a minimal security header set that shouldn't break local dev.
    """
    response = await call_next(request)

    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self' 'unsafe-inline' data: blob:; img-src * data: blob:; media-src *",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")

    return response


# ------------------------------------------------------------
# Frontend static files and SPA routing
# ------------------------------------------------------------

app.mount(
    "/frontend",
    StaticFiles(directory=str(FRONTEND_DIR), html=True),
    name="frontend",
)

# Routers
app.include_router(ops_ledger.router)
app.include_router(health_ready.router)
app.include_router(legacy_frontend_router)
app.include_router(auth_session_apply.router, prefix="/auth")
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
app.include_router(roles.router)
app.include_router(disputes_api.router)
app.include_router(groups.router)
app.include_router(messaging.router)    # /messaging/... + legacy /content alias
app.include_router(sync.router)         # sync / p2p wiring
app.include_router(ledger.router)       # ledger inspection endpoints
app.include_router(storage.router)      # /storage/... (IPFS / local)
app.include_router(p2p_overlay.router)  # /p2p/... identity & peers
app.include_router(content.router)
app.include_router(disputes.router)
app.include_router(pinning.router)
app.include_router(verification.router)
app.include_router(chain.router)
app.include_router(compat.router)
app.include_router(node_meta.router)
app.include_router(health_router.router, prefix="/api/health")


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


# ------------------------------------------------------------
# /auth/email – dev email-code login
# ------------------------------------------------------------

class EmailAuthStart(BaseModel):
    email: str = Field(..., max_length=320)


class EmailAuthVerify(BaseModel):
    email: str = Field(..., max_length=320)
    code: str = Field(..., min_length=4, max_length=12)


_AUTH_CODES: Dict[str, str] = {}
_AUTH_CODES_EXPIRY: Dict[str, float] = {}


def _hash_code(code: str, salt: Optional[str] = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 100_000)
    return salt + ":" + binascii.hexlify(dk).decode()


def _verify_code(code: str, stored: str) -> bool:
    try:
        salt, hex_hash = stored.split(":", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 100_000)
    return binascii.hexlify(dk).decode() == hex_hash


def _send_email_dev_logger(to: str, subject: str, body: str) -> None:
    """
    Dev fallback: log auth email instead of sending real mail.
    """
    print(f"[DEV EMAIL] To: {to}\nSubject: {subject}\n\n{body}\n")


def _send_email_smtp(
    to: str,
    subject: str,
    body: str,
    host: str,
    port: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_tls: bool = True,
) -> None:
    msg = EmailMessage()
    msg["From"] = username or "no-reply@weall.local"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    if use_tls:
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            if username and password:
                server.login(username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as server:
            if username and password:
                server.login(username, password)
            server.send_message(msg)


def _send_email(to: str, subject: str, body: str) -> None:
    host = os.getenv("WEALL_SMTP_HOST")
    port = os.getenv("WEALL_SMTP_PORT")
    user = os.getenv("WEALL_SMTP_USER")
    pw = os.getenv("WEALL_SMTP_PASS")

    if not host or not port:
        _send_email_dev_logger(to, subject, body)
        return

    try:
        _send_email_smtp(
            to=to,
            subject=subject,
            body=body,
            host=host,
            port=int(port),
            username=user,
            password=pw,
        )
    except Exception as e:
        print(f"[SMTP ERROR] {e}")
        _send_email_dev_logger(to, subject, body)


@app.post("/auth/email/start", response_model=dict)
async def auth_start(payload: EmailAuthStart):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email")

    code = f"{secrets.randbelow(1_000_000):06d}"
    _AUTH_CODES[email] = _hash_code(code)
    _AUTH_CODES_EXPIRY[email] = time.time() + 15 * 60

    subject = "Your WeAll sign-in code"
    body = f"Your sign-in code is: {code}\n\nThis code will expire in 15 minutes."
    _send_email(email, subject, body)

    return {"ok": True}


@app.post("/auth/email/verify", response_model=dict)
async def auth_verify(payload: EmailAuthVerify):
    email = payload.email.strip().lower()
    code = payload.code.strip()

    if not email or not code:
        raise HTTPException(status_code=400, detail="Missing email or code")

    stored = _AUTH_CODES.get(email)
    if not stored:
        raise HTTPException(status_code=400, detail="No code issued for this email")

    expiry = _AUTH_CODES_EXPIRY.get(email, 0)
    if time.time() > expiry:
        raise HTTPException(status_code=400, detail="Code expired")

    if not _verify_code(code, stored):
        raise HTTPException(status_code=400, detail="Invalid code")

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
