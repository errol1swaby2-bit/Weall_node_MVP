from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from weall_node.security.tokens import issue_token, verify_token

router = APIRouter(tags=["auth"])

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
