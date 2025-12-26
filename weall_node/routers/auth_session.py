# weall_node/weall_node/routers/auth_session.py
from __future__ import annotations

from typing import Optional, Literal
import hashlib
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from weall_node.security.tokens import issue_token, verify_token
from weall_node.security import auth_db
from weall_node.security.hasher import hash_password, verify_password
from weall_node.weall_executor import executor

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------
# Legacy token endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------

class ApplyReq(BaseModel):
    account_id: str
    scope: Optional[str] = "session"


class ApplyResp(BaseModel):
    token: str
    expires: int


class CheckReq(BaseModel):
    token: str
    scope: Optional[str] = "session"


class CheckResp(BaseModel):
    ok: bool
    subject: Optional[str] = None
    expires: Optional[int] = None


@router.post("/auth/apply", response_model=ApplyResp)
async def auth_apply(body: ApplyReq):
    acct = (body.account_id or "").strip()
    if not acct:
        raise HTTPException(status_code=400, detail="account_id required")
    t = issue_token(acct)
    return {"token": t["token"], "expires": t["expires"]}


@router.post("/auth/check", response_model=CheckResp)
async def auth_check(body: CheckReq):
    p = verify_token(body.token)
    if not p:
        return {"ok": False}
    return {"ok": True, "subject": p.get("sub"), "expires": p.get("exp")}


# ---------------------------------------------------------------------
# Cookie-session auth (preferred for app)
# ---------------------------------------------------------------------

BanDestination = Literal["public_treasury", "group_treasury"]


class RegisterReq(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=256)
    ban_destination: BanDestination = "public_treasury"
    ban_group_id: Optional[str] = Field(default=None, description="Required if ban_destination=group_treasury")


class AuthResp(BaseModel):
    ok: bool
    user_id: str
    session_id: str


class LoginReq(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=256)


class LogoutResp(BaseModel):
    ok: bool


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _derive_user_id(email: str) -> str:
    """
    Deterministic, non-PII user_id derived from normalized email.
    (Email still stored in auth DB for login; user_id avoids exposing email.)
    """
    e = _normalize_email(email)
    digest = hashlib.sha256(e.encode("utf-8")).hexdigest()
    return f"user_{digest[:24]}"


def _set_session_cookie(resp: Response, session_id: str) -> None:
    # Termux/dev friendly defaults; tighten for prod as needed
    resp.set_cookie(
        key="weall_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,  # set True behind HTTPS
        max_age=auth_db.DEFAULT_SESSION_TTL_SEC,
    )


def _clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(key="weall_session")


def _store_ban_policy_in_ledger(user_id: str, ban_destination: str, ban_group_id: Optional[str]) -> None:
    led = getattr(executor, "ledger", None)
    if not isinstance(led, dict):
        return
    accounts = led.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        led["accounts"] = {}
        accounts = led["accounts"]

    acct = accounts.setdefault(user_id, {})
    if not isinstance(acct, dict):
        accounts[user_id] = {}
        acct = accounts[user_id]

    acct["ban_destination"] = str(ban_destination)
    acct["ban_group_id"] = ban_group_id


@router.post("/auth/register", response_model=AuthResp)
async def register(body: RegisterReq, resp: Response):
    email = _normalize_email(body.email)
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    if body.ban_destination == "group_treasury" and not (body.ban_group_id or "").strip():
        raise HTTPException(status_code=400, detail="ban_group_id required when ban_destination=group_treasury")

    existing = auth_db.get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=409, detail="email already registered")

    user_id = _derive_user_id(email)
    now = time.time()

    pw_hash = hash_password(body.password)
    auth_db.create_user(user_id=user_id, email=email, password_hash=pw_hash, now=now)

    # Store ban policy in ledger (spec §3.3 style)
    _store_ban_policy_in_ledger(user_id, body.ban_destination, (body.ban_group_id or None))

    # Create session + set cookie
    sid = auth_db.create_session(user_id=user_id, now=now)
    _set_session_cookie(resp, sid)

    return {"ok": True, "user_id": user_id, "session_id": sid}


@router.post("/auth/login", response_model=AuthResp)
async def login(body: LoginReq, resp: Response):
    email = _normalize_email(body.email)
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    user = auth_db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="invalid credentials")

    if not verify_password(body.password, str(user["password_hash"])):
        raise HTTPException(status_code=401, detail="invalid credentials")

    now = time.time()
    auth_db.update_user_login(str(user["user_id"]), now=now)
    sid = auth_db.create_session(user_id=str(user["user_id"]), now=now)
    _set_session_cookie(resp, sid)

    return {"ok": True, "user_id": str(user["user_id"]), "session_id": sid}


@router.post("/auth/logout", response_model=LogoutResp)
async def logout(resp: Response):
    # We clear cookie client-side; server-side session cleanup is optional here.
    _clear_session_cookie(resp)
    return {"ok": True}
