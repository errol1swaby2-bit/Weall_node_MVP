"""
Proof of Humanity (PoH) API + blockchain-backed state management.

Tiers:
- Tier 1: email verification (mocked sender)
- Tier 2: async juror verification → NFT minted
- Tier 3: live juror verification → NFT minted

Notes:
- Production-ready JSON endpoints via Pydantic models.
- Tier requirements scale dynamically with network size.
- State rebuilt from on-chain history at startup.
- Global memory state (STATE, PENDING_EMAILS, SESSIONS) is process-local.
"""

from __future__ import annotations
import random, string, time, logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from weall_node.app_state import chain, ledger

# -------------------------------
# In-memory state
# -------------------------------
STATE: Dict[str, dict] = {}          # user_id -> {tier, status, badges}
PENDING_EMAILS: Dict[str, dict] = {} # user_id -> {email, code, timestamp}
SESSIONS: Dict[str, dict] = {}       # session_id -> session data

# -------------------------------
# Config
# -------------------------------
CODE_EXPIRY = 15 * 60     # 15 minutes
REQ_COOLDOWN = 60         # cooldown between requests
logger = logging.getLogger("poh")

router = APIRouter(prefix="/poh", tags=["Proof of Humanity"])


# -------------------------------
# Helpers
# -------------------------------
def _send_email(to_addr: str, code: str):
    """Mock email sender (replace in production)."""
    logger.info("[MOCK EMAIL] Sending Tier-1 code to %s: %s", to_addr, code)

def _generate_code(length=6) -> str:
    return "".join(random.choices(string.digits, k=length))

def _get_balance(user: str) -> float:
    """Return ledger balance safely."""
    for method in ("get_balance", "_get"):
        fn = getattr(ledger, method, None)
        if fn:
            try:
                return float(fn(user))
            except Exception:
                pass
    return 0.0

def jurors_required(total_users: int) -> int:
    """Scale juror requirements with network size."""
    if total_users <= 1: return 0
    if total_users <= 2: return 1
    if total_users <= 6: return 2
    if total_users <= 20: return 3
    if total_users <= 40: return 5
    return 10


# -------------------------------
# Chain replay
# -------------------------------
def rebuild_state_from_chain():
    """Rebuild PoH state from blockchain transactions."""
    global STATE
    STATE = {}
    for block in chain.all_blocks():
        for tx in block["txs"]:
            user = tx.get("user")
            if not user:
                continue
            ttype = tx.get("type")
            if ttype == "POH_TIER1":
                STATE[user] = {"tier": 1, "status": "verified", "badges": ["Tier-1 Verified", "NFT minted"]}
            elif ttype == "POH_TIER2_VERIFY" and tx.get("approved"):
                STATE[user] = {"tier": 2, "status": "verified", "badges": ["Tier-2 Verified (NFT)"]}
            elif ttype == "POH_TIER3_VERIFY" and tx.get("approved"):
                STATE[user] = {"tier": 3, "status": "verified", "badges": ["Tier-3 Verified (NFT)"]}

    for user, data in STATE.items():
        data.setdefault("badges", [])


# -------------------------------
# Tier 1 Verification
# -------------------------------
def verify_tier1(user: str):
    """Add Tier-1 verification transaction."""
    for block in chain.all_blocks():
        for tx in block["txs"]:
            if tx.get("type") == "POH_TIER1" and tx.get("user") == user:
                return {"ok": True, "user": user, "tier": 1, "status": "already_registered"}

    ledger.create_account(user)
    tx = {"type": "POH_TIER1", "user": user}
    block = chain.add_block([tx])

    nft_id = f"POH_T1::{user}::{int(time.time())}"
    if hasattr(ledger, "record_mint_event"):
        ledger.record_mint_event(user, nft_id)

    STATE[user] = {"tier": 1, "status": "verified", "badges": ["Tier-1 Verified", "NFT minted"]}
    return {"ok": True, "user": user, "tier": 1, "block": block["hash"], "nft": nft_id}


# -------------------------------
# Tier 2 Verification
# -------------------------------
def apply_tier2(user: str, evidence: str):
    """Request or auto-approve Tier-2 verification."""
    if STATE.get(user, {}).get("tier", 0) < 1:
        return {"ok": False, "error": "Tier-1 required first"}

    total_users = sum(isinstance(u, str) for u in STATE.keys())
    required = jurors_required(total_users)

    if required == 0:
        tx = {"type": "POH_TIER2_VERIFY", "user": user, "approved": True, "evidence": evidence}
        block = chain.add_block([tx])
        nft_id = f"POH_T2::{user}::{int(time.time())}"
        if hasattr(ledger, "record_mint_event"):
            ledger.record_mint_event(user, nft_id)
        rebuild_state_from_chain()
        return {"ok": True, "tier": 2, "status": "auto-approved", "block": block["hash"], "nft": nft_id}

    jurors = [u for u, d in STATE.items() if d.get("tier", 0) >= 3]
    if len(jurors) < required:
        return {"ok": True, "status": "waiting_for_jurors", "available": len(jurors), "required": required}

    selected = random.sample(jurors, required)
    session_id = f"{user}:tier2:{int(time.time())}"
    SESSIONS[session_id] = {"jurors": selected, "votes": {}, "tier": 2, "status": "pending", "required": required}
    return {"ok": True, "session": session_id, "jurors": selected, "required": required}


def verify_tier2(user: str, approver: str, approve: bool):
    """Minimal Tier-2 juror approval hook."""
    if STATE.get(user, {}).get("tier", 0) < 1:
        return {"approved": False, "error": "Tier-1 required first"}
    if not approve:
        return {"approved": False}

    tx = {"type": "POH_TIER2_VERIFY", "user": user, "approved": True, "approver": approver}
    block = chain.add_block([tx])
    nft_id = f"POH_T2::{user}::{int(time.time())}"
    if hasattr(ledger, "record_mint_event"):
        ledger.record_mint_event(user, nft_id)
    rebuild_state_from_chain()
    return {"approved": True, "block": block["hash"], "nft": nft_id}


# -------------------------------
# Tier 3 Verification
# -------------------------------
def verify_tier3(user: str, video_proof: str):
    """Tier-3 verification with juror voting or auto-approval."""
    if STATE.get(user, {}).get("tier", 0) < 2:
        return {"ok": False, "error": "Tier-2 required first"}

    total_users = sum(isinstance(u, str) for u in STATE.keys())
    required = jurors_required(total_users)

    if required == 0:
        tx = {"type": "POH_TIER3_VERIFY", "user": user, "approved": True, "video_proof": video_proof}
        block = chain.add_block([tx])
        nft_id = f"POH_T3::{user}::{int(time.time())}"
        if hasattr(ledger, "record_mint_event"):
            ledger.record_mint_event(user, nft_id)
        rebuild_state_from_chain()
        return {"ok": True, "tier": 3, "status": "auto-approved", "block": block["hash"], "nft": nft_id}

    jurors = [u for u, d in STATE.items() if d.get("tier", 0) >= 3]
    if len(jurors) < required:
        return {"ok": True, "status": "waiting_for_jurors", "available": len(jurors), "required": required}

    selected = random.sample(jurors, required)
    session_id = f"{user}:tier3:{int(time.time())}"
    SESSIONS[session_id] = {"jurors": selected, "attestations": [], "tier": 3, "status": "pending",
                            "required": required, "video_proof": video_proof, "user_id": user}
    return {"ok": True, "session": session_id, "jurors": selected, "required": required}


# -------------------------------
# Tier 3 live-session handling
# -------------------------------
def juror_attest(session_id: str, juror_id: str, decision: bool) -> dict:
    s = SESSIONS.get(session_id)
    if not s or s.get("status") != "pending":
        raise ValueError("Invalid or non-pending session.")
    if juror_id not in s["jurors"]:
        raise ValueError("Juror not authorized.")
    if any(a["juror_id"] == juror_id for a in s["attestations"]):
        raise ValueError("Juror already attested.")
    s["attestations"].append({"juror_id": juror_id, "ts": int(time.time()), "decision": bool(decision)})
    return {"ok": True, "attestations": len(s["attestations"])}


def finalize_tier3(session_id: str) -> dict:
    s = SESSIONS.get(session_id)
    if not s or s.get("status") != "pending":
        raise ValueError("Invalid or non-pending session.")
    approvals = sum(1 for a in s["attestations"] if a["decision"])
    s["status"] = "closed"
    user = s.get("user_id")
    if approvals >= s.get("required", 3):
        tx = {"type": "POH_TIER3_VERIFY", "user": user, "approved": True, "session": session_id}
        block = chain.add_block([tx])
        nft_id = f"POH_T3::{user}::{int(time.time())}"
        if hasattr(ledger, "record_mint_event"):
            ledger.record_mint_event(user, nft_id)
        rebuild_state_from_chain()
        return {"approved": True, "tier": 3, "approvals": approvals, "block": block["hash"], "nft": nft_id}
    return {"approved": False, "tier": 3, "approvals": approvals}


# -------------------------------
# Status
# -------------------------------
def status(user: str):
    data = STATE.get(user)
    if not data:
        return {"ok": False, "error": "User not found"}
    return {"ok": True, "user": user, "tier": data.get("tier"), "status": data.get("status", "unknown"),
            "badges": data.get("badges", []), "balance": _get_balance(user)}


# -------------------------------
# FastAPI Models
# -------------------------------
class Tier1Request(BaseModel): user: str; email: str
class Tier1Verify(BaseModel): user: str; code: str
class Tier2Request(BaseModel): user: str; evidence: str
class Tier3Request(BaseModel): user: str; video_proof: str


# -------------------------------
# Routes
# -------------------------------
@router.post("/request-tier1")
def api_request_tier1(req: Tier1Request, background: BackgroundTasks):
    now = time.time()
    if (p := PENDING_EMAILS.get(req.user)) and now - p["timestamp"] < REQ_COOLDOWN:
        raise HTTPException(status_code=429, detail="Cooldown active — try again soon")

    code = _generate_code()
    PENDING_EMAILS[req.user] = {"email": req.email, "code": code, "timestamp": now}
    background.add_task(_send_email, req.email, code)
    return {"ok": True, "message": f"Verification code sent to {req.email} (mocked)"}


@router.post("/verify-tier1")
def api_verify_tier1(req: Tier1Verify):
    p = PENDING_EMAILS.get(req.user)
    if not p:
        raise HTTPException(status_code=400, detail="No pending verification")
    if time.time() - p["timestamp"] > CODE_EXPIRY:
        del PENDING_EMAILS[req.user]
        raise HTTPException(status_code=400, detail="Code expired")
    if req.code != p["code"]:
        raise HTTPException(status_code=400, detail="Invalid code")

    del PENDING_EMAILS[req.user]
    return verify_tier1(req.user)


@router.post("/tier2")
def api_apply_tier2(req: Tier2Request): return apply_tier2(req.user, req.evidence)


@router.post("/tier3")
def api_verify_tier3(req: Tier3Request): return verify_tier3(req.user, req.video_proof)


@router.get("/status/{user}")
def api_status(user: str): return status(user)


# Startup hook
@router.on_event("startup")
def init_state(): rebuild_state_from_chain()
