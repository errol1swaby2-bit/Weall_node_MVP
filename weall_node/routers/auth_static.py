from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict

router = APIRouter(tags=["auth"])
DEV_CODE = "123456"

async def _read_loose_body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        form = await request.form()
        return {k: v for k, v in form.items()}
    except Exception:
        pass
    return {}

@router.post("/auth/start")
async def auth_start(request: Request):
    d = await _read_loose_body(request)
    email = str(d.get("email") or d.get("user") or d.get("address") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    return {"ok": True, "message": f"Code sent to {email} (dev stub)."}

@router.post("/auth/verify")
async def auth_verify(request: Request):
    d = await _read_loose_body(request)
    # email is OPTIONAL in dev; keep if present
    email = str(d.get("email") or d.get("user") or d.get("address") or "").strip()
    code  = str(d.get("code")  or d.get("otp")  or d.get("verification_code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    if code != DEV_CODE:
        raise HTTPException(status_code=400, detail="Invalid code")
    return {"ok": True, "message": "Verified (dev stub).", "email": email or None}
