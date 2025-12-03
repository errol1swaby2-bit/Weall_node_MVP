"""
weall_node/api/recovery.py
--------------------------------------------------
Email-based account recovery for WeAll.

Endpoints:
- POST /recovery/request  -> send code to email
- POST /recovery/verify   -> verify code & restore keys
"""

import random, string, time, logging
from typing import Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("recovery")

router = APIRouter(prefix="/recovery", tags=["Account Recovery"])

# In-memory state (simple dev version)
PENDING: Dict[str, dict] = {}
RECOVERY_CODES: Dict[str, dict] = {}
CODE_EXPIRY = 15 * 60  # 15 minutes


# -------------------------------
# Helpers
# -------------------------------
def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _send_email(to_addr: str, code: str):
    """Mock email sender (in production integrate SMTP or mail API)."""
    logger.info(f"[MOCK EMAIL] Sending recovery code to {to_addr}: {code}")


# -------------------------------
# Models
# -------------------------------
class RecoveryRequest(BaseModel):
    email: str


class RecoveryVerify(BaseModel):
    email: str
    code: str


# -------------------------------
# Routes
# -------------------------------
@router.post("/request")
def request_recovery(req: RecoveryRequest):
    now = time.time()
    email = req.email.lower().strip()
    code = _generate_code()
    RECOVERY_CODES[email] = {"code": code, "ts": now}
    _send_email(email, code)
    logger.info(f"[Recovery] Code generated for {email}")
    return {"ok": True, "message": "Recovery code sent (mocked)."}


@router.post("/verify")
def verify_recovery(req: RecoveryVerify):
    email = req.email.lower().strip()
    rec = RECOVERY_CODES.get(email)
    if not rec:
        raise HTTPException(status_code=400, detail="No recovery in progress")
    if time.time() - rec["ts"] > CODE_EXPIRY:
        del RECOVERY_CODES[email]
        raise HTTPException(status_code=400, detail="Code expired")
    if req.code.strip().upper() != rec["code"]:
        raise HTTPException(status_code=400, detail="Invalid code")

    # Generate new keys (placeholder)
    pub = f"user_{''.join(random.choices(string.ascii_lowercase, k=8))}"
    priv = "".join(random.choices(string.ascii_letters + string.digits, k=32))
    creds = {"public": pub, "private": priv}

    del RECOVERY_CODES[email]
    logger.info(f"[Recovery] Account restored for {email} as {pub}")
    return {"ok": True, "message": "Account recovered.", "new_credentials": creds}
