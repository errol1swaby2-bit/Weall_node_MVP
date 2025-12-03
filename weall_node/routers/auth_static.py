from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict
import os

router = APIRouter(tags=["auth"])

DEV_CODE = "123456"
DEV_MODE = os.getenv("WEALL_ENV", "dev").lower() != "prod"


async def _read_loose_body(request: Request) -> Dict[str, Any]:
    """Accept either JSON or form-encoded bodies and normalize to a dict."""
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
        return {}


@router.post("/auth/send-code")
async def auth_send_code(request: Request):
    """Dev-only: pretend to send an email/SMS verification code.

    In production (WEALL_ENV=prod), this route is disabled and returns 404.
    A real mailer / OTP flow should be wired instead.
    """
    if not DEV_MODE:
        raise HTTPException(status_code=404, detail="Not available in this environment")

    d = await _read_loose_body(request)
    email = str(d.get("email") or d.get("user") or d.get("address") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    return {"ok": True, "message": f"Code sent to {email} (dev stub)."}


@router.post("/auth/verify")
async def auth_verify(request: Request):
    """Dev-only: accept a fixed OTP code for verification.

    In production (WEALL_ENV=prod), this route is disabled and returns 404.
    """
    if not DEV_MODE:
        raise HTTPException(status_code=404, detail="Not available in this environment")

    d = await _read_loose_body(request)
    email = str(d.get("email") or d.get("user") or d.get("address") or "").strip()
    code = str(
        d.get("code") or d.get("otp") or d.get("verification_code") or ""
    ).strip()

    if not code:
        raise HTTPException(status_code=400, detail="code required")
    if code != DEV_CODE:
        raise HTTPException(status_code=400, detail="Invalid code")

    return {"ok": True, "message": "Verified (dev stub).", "email": email or None}
