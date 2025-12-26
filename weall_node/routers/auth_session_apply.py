from __future__ import annotations

import re
import time
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..security import auth_db, hasher
from ..security.current_user import current_user_id_from_cookie_optional
from ..weall_executor import executor
from ..weall_runtime import poh_flow
from ..weall_runtime.genesis_mode import try_bootstrap_first_user


router = APIRouter(tags=["auth"])

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{1,30}$")


def _normalize_handle(raw: str) -> str:
    v = (raw or "").strip()
    if v.startswith("@"):  # tolerate either form
        v = v[1:]
    if not _HANDLE_RE.match(v):
        raise HTTPException(status_code=400, detail="invalid_handle")
    return "@" + v


class AuthApplyRequest(BaseModel):
    # compat: frontend sometimes sends handle, sometimes userId
    user_id: Optional[str] = None
    handle: Optional[str] = None
    email: Optional[str] = None
    password: str


class AuthSessionResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    poh_id: Optional[str] = None
    created_at: float
    last_login_at: Optional[float] = None


@router.post("/apply", response_model=AuthSessionResponse)
async def auth_apply(payload: AuthApplyRequest, request: Request, response: Response):
    """
    Cookie-backed login / signup.

    - Creates user on first login, otherwise verifies password.
    - Creates a durable session row in auth_db and sets cookie `weall_session`.
    - Ensures PoH tier-1 record exists.
    - In genesis mode: optionally bootstraps first user (never blocks login).
    """

    now = time.time()

    handle = payload.handle or payload.user_id
    if not handle:
        raise HTTPException(status_code=400, detail="missing_handle")
    user_id = _normalize_handle(handle)

    user = auth_db.get_user_by_id(user_id)
    if not user:
        user = auth_db.create_user(
            user_id=user_id,
            email=payload.email,
            password_hash=hasher.hash_password(payload.password),
            now=now,
        )
    else:
        if not hasher.verify_password(payload.password, user.get("password_hash") or ""):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        auth_db.update_user_login(user_id, now=now)

    # --------------------------------------------------------------
    # ENSURE PoH RECORD (Tier-1 unlock)
    # --------------------------------------------------------------
    rec = poh_flow.ensure_poh_record(executor.ledger, user_id)
    if rec.get("tier", 0) < 1:
        rec["tier"] = 1
        rec.setdefault("history", []).append({
            "ts": int(now),
            "event": "auto_tier1_on_auth",
        })

    # Create session and set cookie.
    sid = auth_db.create_session(user_id=user_id, now=now)

    # --------------------------------------------------------------
    # Genesis Mode (one-time bootstrap for first user)
    # --------------------------------------------------------------
    try:
        try_bootstrap_first_user(executor.ledger, user_id)
    except Exception:
        # never block login due to genesis helper
        pass

    response.set_cookie(
        "weall_session",
        sid,
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https"),
        path="/",
    )

    return AuthSessionResponse(
        user_id=user_id,
        email=user.get("email"),
        poh_id=user.get("poh_id"),
        created_at=float(user.get("created_at", now)),
        last_login_at=float(user.get("last_login_at")) if user.get("last_login_at") else None,
    )


@router.get("/session", response_model=AuthSessionResponse)
async def auth_session(
    user_id: Optional[str] = Depends(current_user_id_from_cookie_optional),
):
    """Return the current cookie session's user (or 401 if not logged in)."""
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    user = auth_db.get_user_by_id(user_id)
    if not user:
        # session exists but user row missing (corruption / manual edits)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    return AuthSessionResponse(
        user_id=user_id,
        email=user.get("email"),
        poh_id=user.get("poh_id"),
        created_at=float(user.get("created_at", 0.0) or 0.0),
        last_login_at=float(user.get("last_login_at")) if user.get("last_login_at") else None,
    )


class LogoutResponse(BaseModel):
    ok: bool = True


@router.post("/logout", response_model=LogoutResponse)
async def auth_logout(
    response: Response,
    session_id: Optional[str] = Cookie(default=None, alias="weall_session"),
):
    """Delete the server session (if any) and clear the cookie."""
    try:
        if session_id:
            auth_db.delete_session(session_id)
    finally:
        response.delete_cookie("weall_session", path="/")
    return LogoutResponse(ok=True)
