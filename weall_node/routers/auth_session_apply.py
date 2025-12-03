from fastapi import APIRouter, HTTPException, Request
from typing import Any, Dict
from ..security.tokens import issue_token, verify_token

router = APIRouter(tags=["auth"])


async def _read_body(request: Request) -> Dict[str, Any]:
    """
    Read JSON or form body and normalize into a dict.
    This mirrors the loose body handling used in other auth routes.
    """
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


@router.post("/auth/apply")
async def auth_apply(request: Request):
    """
    Final step in the login flow:
    - Takes an account identifier (email / account_id / user_id)
    - Issues a signed session token
    - Returns { ok, token, expires }

    The frontend should store this token and send it on subsequent API calls.
    """
    d = await _read_body(request)
    subject = str(
        d.get("account_id")
        or d.get("email")
        or d.get("user_id")
        or d.get("user")
        or ""
    ).strip()

    if not subject:
        raise HTTPException(status_code=400, detail="account_id or email required")

    token_info = issue_token(subject)
    return {
        "ok": True,
        "token": token_info["token"],
        "expires": token_info["expires"],
        "subject": subject,
    }


@router.post("/auth/check")
async def auth_check(request: Request):
    """
    Validate an existing token and return its subject + expiry.

    Body may contain:
    - { "token": "<token>" }
    or token can be passed as 'Authorization: Bearer <token>' header later
    (for now we just support body, to stay aligned with the current frontend).
    """
    d = await _read_body(request)
    token = str(d.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token required")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid or expired token")

    return {
        "ok": True,
        "subject": payload.get("sub"),
        "expires": payload.get("exp"),
    }
