# weall_node/routers/auth_session_apply.py
from __future__ import annotations

"""
Auth + session router for WeAll.

This module provides a minimal, production-grade auth flow:

- POST /auth/apply
    Unified "login or register" endpoint. If the user_id/handle does not
    exist yet, a new account record is created. If it exists, the password
    is verified and a session is created.

- GET /auth/session
    Return the current authenticated user from the session cookie, if any.

- POST /auth/logout
    Clear the session cookie and remove the server-side session record.

Notes
-----
* This router is intentionally **agnostic** about PoH tiers, keys, and
  recovery. It deals strictly with application-level accounts and
  sessions. PoH and recovery live in their respective modules.

* Passwords are stored as salted hashes using the shared `hasher` module.

* The session store is backed by `executor.ledger["auth"]["sessions"]`
  with a simple in-memory (but persisted-to-disk) structure. For a real
  production deployment, you may want to plug in Redis or another external
  session store.
"""

import secrets
import time
from typing import Dict, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..security import hasher

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------


def _ensure_auth_ledger() -> Dict[str, Dict[str, dict]]:
    """
    Ensure the auth namespace exists in executor.ledger.

    Structure:

    executor.ledger["auth"] = {
        "users": {
            user_id: {
                "user_id": str,
                "password_hash": str,
                "created_at": float,
                "last_login_at": float | None,
                "poh_id": str | None,
            },
            ...
        },
        "sessions": {
            session_id: {
                "session_id": str,
                "user_id": str,
                "created_at": float,
                "last_seen_at": float,
            },
            ...
        },
    }
    """
    ledger = executor.ledger
    auth_ns = ledger.setdefault("auth", {})
    auth_ns.setdefault("users", {})
    auth_ns.setdefault("sessions", {})
    return auth_ns  # type: ignore[return-value]


def _get_user_record(user_id: str) -> Optional[dict]:
    auth_ns = _ensure_auth_ledger()
    return auth_ns["users"].get(user_id)


def _set_user_record(user_id: str, record: dict) -> None:
    auth_ns = _ensure_auth_ledger()
    auth_ns["users"][user_id] = record
    _maybe_save_state()


def _get_session(session_id: str) -> Optional[dict]:
    auth_ns = _ensure_auth_ledger()
    return auth_ns["sessions"].get(session_id)


def _create_session(user_id: str) -> str:
    auth_ns = _ensure_auth_ledger()
    sid = secrets.token_hex(16)
    now = time.time()
    auth_ns["sessions"][sid] = {
        "session_id": sid,
        "user_id": user_id,
        "created_at": now,
        "last_seen_at": now,
    }
    _maybe_save_state()
    return sid


def _delete_session(session_id: str) -> None:
    auth_ns = _ensure_auth_ledger()
    if session_id in auth_ns["sessions"]:
        del auth_ns["sessions"][session_id]
        _maybe_save_state()


def _maybe_save_state() -> None:
    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AuthApplyRequest(BaseModel):
    user_id: str = Field(
        ...,
        description=(
            "User handle / ID. May be prefixed with '@'. "
            "Will be normalized to '@handle' form."
        ),
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Plain-text password. Will be hashed before storage.",
    )


class AuthSessionResponse(BaseModel):
    user_id: str
    poh_id: Optional[str] = None
    created_at: float
    last_login_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Dependency: current user from session
# ---------------------------------------------------------------------------


def get_current_user(
    session_id: Optional[str] = Cookie(default=None, alias="weall_session"),
) -> Optional[dict]:
    """
    Resolve the current user from the `weall_session` cookie.

    Returns:
        - A user record dict if a valid session exists.
        - None if no session/cookie is present.
    """
    if not session_id:
        return None
    sess = _get_session(session_id)
    if not sess:
        return None
    user = _get_user_record(sess["user_id"])
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _normalize_user_id(raw: str) -> str:
    v = (raw or "").strip()
    if not v:
        raise HTTPException(status_code=400, detail="user_id cannot be blank.")
    if not v.startswith("@"):
        v = "@" + v
    return v


@router.post("/apply", response_model=AuthSessionResponse)
def auth_apply(payload: AuthApplyRequest, response: Response) -> AuthSessionResponse:
    """
    Unified "login or register" entrypoint.

    Behavior:
    - If user_id does not exist:
        - Create a new user with a hashed password.
        - Create a session and set the `weall_session` cookie.
    - If user_id exists:
        - Verify the password.
        - Update last_login_at.
        - Create a new session and set the cookie.
    """
    user_id = _normalize_user_id(payload.user_id)
    record = _get_user_record(user_id)
    now = time.time()

    if record is None:
        # --- Register new user ---
        pwd_hash = hasher.hash_password(payload.password)
        record = {
            "user_id": user_id,
            "password_hash": pwd_hash,
            "created_at": now,
            "last_login_at": now,
            "poh_id": None,  # can be filled by PoH system later
        }
        _set_user_record(user_id, record)
    else:
        # --- Login existing user ---
        stored = record.get("password_hash") or ""
        if not hasher.verify_password(payload.password, stored):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        record["last_login_at"] = now
        _set_user_record(user_id, record)

    # Create session
    session_id = _create_session(user_id)
    # Cookie: secure flags should be set via middleware / deployment config
    response.set_cookie(
        "weall_session",
        session_id,
        httponly=True,
        samesite="lax",
        # secure=True  # enable when HTTPS is enforced
    )

    return AuthSessionResponse(
        user_id=user_id,
        poh_id=record.get("poh_id"),
        created_at=record["created_at"],
        last_login_at=record.get("last_login_at"),
    )


@router.get("/session", response_model=AuthSessionResponse)
def get_session(current_user: dict = Depends(get_current_user)) -> AuthSessionResponse:
    """
    Return information about the currently authenticated user.

    If no valid session cookie is present, returns 401.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return AuthSessionResponse(
        user_id=current_user["user_id"],
        poh_id=current_user.get("poh_id"),
        created_at=float(current_user.get("created_at", 0.0)),
        last_login_at=(
            float(current_user["last_login_at"])
            if current_user.get("last_login_at") is not None
            else None
        ),
    )


@router.post("/logout")
def logout(
    response: Response,
    session_id: Optional[str] = Cookie(default=None, alias="weall_session"),
) -> Dict[str, str]:
    """
    Clear the current session (if any) and delete the cookie.
    """
    if session_id:
        _delete_session(session_id)
    response.delete_cookie("weall_session")
    return {"ok": "logged out"}
