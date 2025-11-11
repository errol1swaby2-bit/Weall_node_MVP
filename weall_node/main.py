from __future__ import annotations

from weall_node.routers.auth_session import router as auth_session_router
from weall_node.routers.auth_static import router as auth_router
from starlette.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import logging
from pathlib import Path
from typing import List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse
# from starlette.staticfiles import StaticFiles

# --- Settings (YAML-backed) ---
try:
    # Prefer local module at repo root
    from weall_settings import settings
except Exception as e:
    # Soft fallback so app can still boot in dev if settings not present yet
    logging.warning("weall_settings not found or failed to load: %s", e)

    class _Fallback:
        class _Server:
            host = "0.0.0.0"
            port = 8000
            cors_origins: List[str] = ["*"]

        class _JWT:
            secret_key = "dev"
            algorithm = "HS256"
            expire_minutes = 60

        class _Log:
            level = "INFO"
            json = True

        server = _Server()
        jwt = _JWT()
        logging = _Log()
        DATA_DIR = Path(".")

    settings = _Fallback()  # type: ignore[assignment]

# --- IPFS client init (safe/no-op if daemon isn't running) ---
from weall_node.ipfs.client import init_default_client  # noqa: E402

# --- Routers ---
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
    compat,  # legacy endpoints (/register, /show_posts, etc.)
)

# ---------------------------
# App initialization
# ---------------------------

app = FastAPI(
    title="WeAll Node API",
    description="Backend node API for WeAll network (governance, PoH, ledger, content, disputes, etc.)",
    version="0.1.0",
)


app.include_router(auth_session_router)
app.include_router(auth_router)
app.mount("/frontend", StaticFiles(directory="weall_node/frontend", html=True), name="frontend")

# CORS (read from YAML/env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(settings.server, "cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Initialize global IPFS client (idempotent; returns None if not available)
# ----------------------------------------------------------
from fastapi.responses import RedirectResponse, Response
import os


@app.get("/index/", include_in_schema=False)
def _redir_index():
    return RedirectResponse(url="/frontend/index.html", status_code=307)


@app.get("/favicon.ico", include_in_schema=False)
def _favicon():
    try:
        with open("favicon.ico", "rb") as f:
            return Response(content=f.read(), media_type="image/x-icon")
    except FileNotFoundError:
        return Response(status_code=404)


# # # # # app.mount("/frontend", StaticFiles(directory="dist", html=True), name="frontend")  # commented by 15_fix_frontend_mount.sh  # commented by 16_fix_frontend_mount_syntax.sh  # commented by 17_repair_frontend_mount_block.sh  # commented by 18_purge_bad_mounts_and_set_single.sh  # commented by 19_fix_mount_parentheses.sh


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """
    Genesis-aligned entrypoint with session-aware routing.

    - API / programmatic clients:
        Get a JSON descriptor (no redirects) for predictable automation.

    - Browsers / humans WITHOUT a session:
        Redirect to onboarding.html (explains PoH tiers & flow).

    - Browsers / humans WITH a session cookie:
        Redirect straight to frontend/index.html (home feed).
    """
    accept = (request.headers.get("accept") or "").lower()
    cookie_header = request.headers.get("cookie") or ""
    cookie_lower = cookie_header.lower()

    # Heuristic: treat these cookies as "logged-in" indicators.
    has_session = any(
        token in cookie_lower
        for token in (
            "weall_session=",
            "session_id=",
            "weall_auth=",
        )
    )

    # API-style clients get JSON instead of redirects
    if "application/json" in accept and "text/html" not in accept:
        return {
            "status": "ok",
            "node": "weall-genesis",
            "message": "WeAll Genesis node online.",
            "onboarding_url": "/frontend/onboarding.html",
            "login_url": "/frontend/login.html",
            "home_url": "/frontend/index.html",
            "spec": {
                "poh_tiers": [1, 2, 3],
                "reputation_range": [-1.0, 1.0],
                "tier3_threshold": 0.75,
            },
        }

    # If we appear to have a session, send user to home feed
    if has_session:
        return RedirectResponse(url="/frontend/index.html", status_code=302)

    # Otherwise show Genesis onboarding
    return RedirectResponse(url="/frontend/onboarding.html", status_code=302)


@app.get("/index", include_in_schema=False)
def _redir_index_noslash():
    return RedirectResponse(url="/frontend/index.html", status_code=307)

# --- Local dev health endpoint ---
@app.get("/api/health")
def health():
    return {"status": "ok"}



# --- WeAll Genesis: mount reputation API (non-invasive) ---------------------
try:
    from weall_node.api import reputation as _reputation_api  # type: ignore
except Exception:
    _reputation_api = None  # type: ignore[assignment]

if _reputation_api is not None:
    try:
        app.include_router(_reputation_api.router)
    except Exception:
        # If it's already mounted or app is wired differently, ignore.
        pass
