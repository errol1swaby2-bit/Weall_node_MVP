from __future__ import annotations

import re
import time
from typing import Dict, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..security import auth_db, hasher
from ..security.current_user import current_user_id_from_cookie_optional

router = APIRouter(tags=["auth"])

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{1,30}$")


def _looks_like_email(v: str) -> bool:
    v = (v or "").strip()
    return ("@" in v) and ("." in v.split("@")[-1])


def _normalize_handle(raw: str) -> str:
    v = (raw or "").strip()
    if v.startswith("@"):
        v = v[1:]
    if not v:
        raise HTTPException(status_code=400, detail="Handle cannot be blank.")
    if not _HANDLE_RE.match(v):
        raise HTTPException(
            status_code=400,
            detail="Invalid handle. Use letters, numbers, underscores, hyphens (2-31 chars).",
        )
    return "@" + v


class AuthApplyRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, description="Handle OR email (login identifier).")
    handle: Optional[str] = Field(default=None, description="Handle for registration (no @ required).")
    email: Optional[str] = Field(default=None, description="Email for registration/login lookup.")
    password: str = Field(..., min_length=1, max_length=256)


class AuthSessionResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    poh_id: Optional[str] = None
    created_at: float
    last_login_at: Optional[float] = None


def _resolve_identifier(payload: AuthApplyRequest) -> Dict[str, Optional[str]]:
    handle = payload.handle
    email = payload.email
    ident = (payload.user_id or "").strip()

    if ident and _looks_like_email(ident):
        email = email or ident
        return {"handle": handle, "email": email, "kind": "email"}

    if ident and not handle:
        handle = ident

    return {"handle": handle, "email": email, "kind": "handle"}


@router.post("/apply", response_model=AuthSessionResponse)
async def auth_apply(payload: AuthApplyRequest, request: Request, response: Response) -> AuthSessionResponse:
    now = time.time()
    info = _resolve_identifier(payload)

    handle_raw = info["handle"]
    email = (info["email"] or "").strip() or None
    kind = info["kind"]

    if kind == "email":
        if not email:
            raise HTTPException(status_code=400, detail="Email is required.")
        user = auth_db.get_user_by_email(email)
        if not user:
            if not handle_raw:
                raise HTTPException(status_code=404, detail="No account found for that email.")
            user_id = _normalize_handle(handle_raw)
            if auth_db.get_user_by_id(user_id):
                raise HTTPException(status_code=409, detail="Handle already exists.")
            user = auth_db.create_user(
                user_id=user_id,
                email=email,
                password_hash=hasher.hash_password(payload.password),
                now=now,
            )
        else:
            if not hasher.verify_password(payload.password, user.get("password_hash") or ""):
                raise HTTPException(status_code=401, detail="Invalid credentials.")
            auth_db.update_user_login(user["user_id"], now=now)
            user = auth_db.get_user_by_id(user["user_id"]) or user
    else:
        if not handle_raw:
            raise HTTPException(status_code=400, detail="Handle is required.")
        user_id = _normalize_handle(handle_raw)

        user = auth_db.get_user_by_id(user_id)
        if not user:
            user = auth_db.create_user(
                user_id=user_id,
                email=email,
                password_hash=hasher.hash_password(payload.password),
                now=now,
            )
        else:
            if not hasher.verify_password(payload.password, user.get("password_hash") or ""):
                raise HTTPException(status_code=401, detail="Invalid credentials.")
            auth_db.update_user_login(user_id, now=now)
            user = auth_db.get_user_by_id(user_id) or user

    sid = auth_db.create_session(user_id=str(user["user_id"]), now=now)

    secure = (request.url.scheme == "https")
    response.set_cookie(
        "weall_session",
        sid,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )

    return AuthSessionResponse(
        user_id=str(user["user_id"]),
        email=user.get("email"),
        poh_id=user.get("poh_id"),
        created_at=float(user.get("created_at", now)),
        last_login_at=float(user["last_login_at"]) if user.get("last_login_at") is not None else None,
    )


@router.get("/session", response_model=AuthSessionResponse)
def get_session(user_id: Optional[str] = Depends(current_user_id_from_cookie_optional)) -> AuthSessionResponse:
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    user = auth_db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return AuthSessionResponse(
        user_id=str(user["user_id"]),
        email=user.get("email"),
        poh_id=user.get("poh_id"),
        created_at=float(user.get("created_at", 0.0)),
        last_login_at=float(user["last_login_at"]) if user.get("last_login_at") is not None else None,
    )


@router.post("/logout")
def logout(
    response: Response,
    session_id: Optional[str] = Cookie(default=None, alias="weall_session"),
) -> Dict[str, str]:
    if session_id:
        auth_db.delete_session(session_id)
    response.delete_cookie("weall_session", path="/")
    return {"ok": "logged out"}
