"""
Proof of Humanity (PoH) API + state management with blockchain persistence.
- Tier-1: email verification (mocked email sender).
- Tier-2: async juror verification (auto when small network) → NFT minted + badge.
- Tier-3: live juror verification → NFT minted + badge.
- Status: returns tier, badges, and ledger balance.

Production-safety tweaks:
- All POST endpoints accept JSON bodies (Pydantic models).
- Guard when there aren’t enough Tier-3 jurors yet (returns waiting_for_jurors).
- Balance lookup uses a safe helper that falls back if ledger.get_balance() is missing.
- Verification minting happens here; higher-level wrappers should NOT mint again.
"""

from __future__ import annotations

import random
import string
import time
from typing import Dict, List

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

# ✅ Use the shared chain + ledger instances from app_state
from weall_node.app_state import chain, ledger

# -------------------------------
# In-memory working state
# -------------------------------
STATE: Dict[str, dict] = {}          # user_id -> {tier, status, badges, ...}
PENDING_EMAILS: Dict[str, dict] = {} # user_id -> {email, code, timestamp}

# -------------------------------
# Config
# -------------------------------
CODE_EXPIRY = 15 * 60     # 15 minutes
REQ_COOLDOWN = 60         # 60 seconds between email requests

router = APIRouter(prefix="/poh", tags=["poh"])


# -------------------------------
# Helpers
# -------------------------------
def _send_email(to_addr: str, code: str):
    """Mock email sender: just logs the code. Replace in prod."""
    print(f"[MOCK EMAIL] Sending PoH Tier-1 code to {to_addr}: {code}")

def _generate_code(length=6) -> str:
    return "".join(random.choices(string.digits, k=length))

def _get_balance(user: str) -> float:
    """Prefer ledger.get_balance if available; else fallback to _get."""
    if hasattr(ledger, "get_balance"):
        try:
            return float(ledger.get_balance(user))
        except Exception:
            pass
    if hasattr(ledger, "_get"):
        try:
            return float(ledger._get(user))
        except Exception:
            pass
    return 0.0

def jurors_required(total_users: int) -> int:
    if total_users <= 1:
        return 0
    elif total_users <= 2:
        return 1
    elif 3 <= total_users <= 6:
        return 2
    elif 7 <= total_users <= 20:
        return 3
    elif 21 <= total_users <= 40:
        return 5
    else:
        return 10


# -------------------------------
# Rebuild state from chain
# -------------------------------
def rebuild_state_from_chain():
    global STATE
    STATE = {}
    for block in chain.all_blocks():
        for tx in block["txs"]:
            ttype = tx.get("type")
            user = tx.get("user")
            if not user:
                continue
            if ttype == "POH_TIER1":
                STATE[user] = {"tier": 1, "status": "verified", "badges": ["Tier-1 Verified", "NFT minted"]}
            elif ttype == "POH_TIER2_VERIFY" and tx.get("approved"):
                STATE[user] = {"tier": 2, "status": "verified", "badges": ["Tier-2 Verified (NFT)"]}
            elif ttype == "POH_TIER3_VERIFY" and tx.get("approved"):
                STATE[user] = {"tier": 3, "status": "verified", "badges": ["Tier-3 Verified (NFT)"]}

    # Ensure badges array exists
    for user, data in STATE.items():
        data.setdefault("badges", [])


# -------------------------------
# Core PoH functions (blockchain-backed)
# -------------------------------
def verify_tier1(user: str):
    # Already verified?
    for block in chain.all_blocks():
        for tx in block["txs"]:
            if tx.get("type") == "POH_TIER1" and tx.get("user") == user:
                return {"ok": True, "user": user, "tier": 1, "status": "already_registered"}

    # Create an account if needed
    if hasattr(ledger, "create_account"):
        ledger.create_account(user)

    # Record T1 on-chain
    tx = {"type": "POH_TIER1", "user": user}
    block = chain.add_block([tx])

    # Mint T1 NFT (record event)
    nft_id = f"POH_T1::{user}::{int(time.time())}"
    if hasattr(ledger, "record_mint_event"):
        ledger.record_mint_event(user, nft_id)

    # Update memory
    STATE[user] = {
        "tier": 1,
        "status": "verified",
        "badges": ["Tier-1 Verified", "NFT minted"],
    }
    return {
        "ok": True,
        "user": user,
        "tier": 1,
        "status": "recorded",
        "block": block["hash"],
        "nft": nft_id,
    }


def apply_tier2(user: str, evidence: str):
    if user not in STATE or STATE[user].get("tier", 0) < 1:
        return {"ok": False, "error": "Tier 1 required first"}

    total_users = len([u for u in STATE.keys() if isinstance(u, str)])
    required = jurors_required(total_users)

    if required == 0:
        # Auto-approve when tiny network
        tx = {"type": "POH_TIER2_VERIFY", "user": user, "approved": True, "juror_votes": {}, "evidence": evidence}
        block = chain.add_block([tx])

        # Mint T2 NFT
        nft_id = f"POH_T2::{user}::{int(time.time())}"
        if hasattr(ledger, "record_mint_event"):
            ledger.record_mint_event(user, nft_id)

        rebuild_state_from_chain()
        return {
            "ok": True,
            "user": user,
            "tier": 2,
            "status": "auto-approved",
            "block": block["hash"],
            "nft": nft_id,
        }

    # Need jurors
    candidates = [u for u, d in STATE.items() if isinstance(u, str) and d.get("tier", 0) >= 3]
    if len(candidates) < required:
        return {
            "ok": True,
            "status": "waiting_for_jurors",
            "available": len(candidates),
            "required": required,
            "hint": "More Tier-3 jurors needed for Tier-2 approvals.",
        }

    selected = random.sample(candidates, required)
    session_id = f"{user}:tier2:{int(time.time())}"
    STATE.setdefault("sessions", {})[session_id] = {
        "jurors": selected,
        "votes": {},         # juror_id -> bool
        "tier": 2,
        "status": "pending",
        "required": required,
        "evidence": evidence,
    }
    return {"ok": True, "session": session_id, "jurors": selected, "required": required}


def verify_tier2(user: str, approver: str, approve: bool):
    """Minimal Tier-2 verification hook for compatibility with wrappers."""
    if user not in STATE or STATE[user].get("tier", 0) < 1:
        return {"approved": False, "error": "Tier 1 required first"}

    if not approve:
        return {"approved": False}

    tx = {"type": "POH_TIER2_VERIFY", "user": user, "approved": True, "approver": approver}
    block = chain.add_block([tx])

    # Mint T2 NFT
    nft_id = f"POH_T2::{user}::{int(time.time())}"
    if hasattr(ledger, "record_mint_event"):
        ledger.record_mint_event(user, nft_id)

    rebuild_state_from_chain()
    return {"approved": True, "block": block["hash"], "nft": nft_id}


def verify_tier3(user: str, video_proof: str):
    if user not in STATE or STATE[user].get("tier", 0) < 2:
        return {"ok": False, "error": "Tier 2 required first"}

    total_users = len([u for u in STATE.keys() if isinstance(u, str)])
    required = jurors_required(total_users)

    if required == 0:
        tx = {"type": "POH_TIER3_VERIFY", "user": user, "approved": True, "video_proof": video_proof}
        block = chain.add_block([tx])

        # Mint T3 NFT
        nft_id = f"POH_T3::{user}::{int(time.time())}"
        if hasattr(ledger, "record_mint_event"):
            ledger.record_mint_event(user, nft_id)

        rebuild_state_from_chain()
        return {
            "ok": True,
            "user": user,
            "tier": 3,
            "status": "auto-approved",
            "block": block["hash"],
            "nft": nft_id,
        }

    # Need jurors
    candidates = [u for u, d in STATE.items() if isinstance(u, str) and d.get("tier", 0) >= 3]
    if len(candidates) < required:
        return {
            "ok": True,
            "status": "waiting_for_jurors",
            "available": len(candidates),
            "required": required,
            "hint": "More Tier-3 jurors needed for Tier-3 approvals.",
        }

    selected = random.sample(candidates, required)
    session_id = f"{user}:tier3:{int(time.time())}"
    STATE.setdefault("sessions", {})[session_id] = {
        "jurors": selected,
        "attestations": [],  # list of {"juror_id","ts","decision":bool}
        "tier": 3,
        "status": "pending",
        "required": required,
        "video_proof": video_proof,
        "user_id": user,
    }
    return {"ok": True, "session": session_id, "jurors": selected, "required": required}


# -------------------------------
# Tier 3 live-session helpers
# -------------------------------
def create_tier3_session(user_id: str, jurors: List[str]) -> dict:
    if len(jurors) < 3:
        raise ValueError("Need at least 3 jurors for MVP.")
    session_id = f"{user_id}:tier3:{int(time.time())}"
    STATE.setdefault("sessions", {})[session_id] = {
        "jurors": list(jurors),
        "attestations": [],
        "tier": 3,
        "status": "pending",
        "required": max(3, min(10, len(jurors))),
        "video_proof": None,
        "user_id": user_id,
    }
    return {"session_id": session_id, "jurors": jurors, "required": STATE["sessions"][session_id]["required"]}

def juror_attest(session_id: str, juror_id: str, decision: bool) -> dict:
    s = STATE.get("sessions", {}).get(session_id)
    if not s or s.get("status") != "pending":
        raise ValueError("Invalid or non-pending session.")
    if juror_id not in s["jurors"]:
        raise ValueError("Juror not authorized for this session.")
    if any(a["juror_id"] == juror_id for a in s["attestations"]):
        raise ValueError("Juror already attested.")
    s["attestations"].append({"juror_id": juror_id, "ts": int(time.time()), "decision": bool(decision)})
    return {"ok": True, "attestations": len(s["attestations"])}

def finalize_tier3(session_id: str) -> dict:
    s = STATE.get("sessions", {}).get(session_id)
    if not s or s.get("status") != "pending":
        raise ValueError("Invalid or non-pending session.")
    approvals = sum(1 for a in s["attestations"] if a["decision"])
    s["status"] = "closed"
    user = s.get("user_id")
    if approvals >= s.get("required", 3):
        # On-chain record
        tx = {"type": "POH_TIER3_VERIFY", "user": user, "approved": True, "session": session_id}
        block = chain.add_block([tx])
        # Mint T3 NFT
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
    if user not in STATE:
        return {"ok": False, "error": "User not found"}
    return {
        "ok": True,
        "user": user,
        "tier": STATE[user].get("tier"),
        "status": STATE[user].get("status", "unknown"),
        "badges": STATE[user].get("badges", []),
        "balance": _get_balance(user),
    }


# -------------------------------
# FastAPI request models
# -------------------------------
class Tier1Request(BaseModel):
    user: str
    email: str

class Tier1Verify(BaseModel):
    user: str
    code: str

class Tier2Request(BaseModel):
    user: str
    evidence: str

class Tier3Request(BaseModel):
    user: str
    video_proof: str


# -------------------------------
# FastAPI Routes (JSON bodies)
# -------------------------------
@router.post("/request-tier1")
def api_request_tier1(req: Tier1Request, background: BackgroundTasks):
    now = time.time()
    pending = PENDING_EMAILS.get(req.user)
    if pending and now - pending["timestamp"] < REQ_COOLDOWN:
        raise HTTPException(status_code=429, detail="Please wait before requesting a new code")

    code = _generate_code()
    PENDING_EMAILS[req.user] = {"email": req.email, "code": code, "timestamp": now}
    background.add_task(_send_email, req.email, code)
    return {"ok": True, "message": f"Verification code sent to {req.email} (check logs in dev mode)"}

@router.post("/verify-tier1")
def api_verify_tier1(req: Tier1Verify):
    pending = PENDING_EMAILS.get(req.user)
    if not pending:
        raise HTTPException(status_code=400, detail="No pending verification")
    if time.time() - pending["timestamp"] > CODE_EXPIRY:
        del PENDING_EMAILS[req.user]
        raise HTTPException(status_code=400, detail="Code expired")
    if req.code != pending["code"]:
        raise HTTPException(status_code=400, detail="Invalid code")

    del PENDING_EMAILS[req.user]
    return verify_tier1(req.user)

@router.post("/tier2")
def api_apply_tier2(req: Tier2Request):
    return apply_tier2(req.user, req.evidence)

@router.post("/tier3")
def api_verify_tier3(req: Tier3Request):
    return verify_tier3(req.user, req.video_proof)

@router.get("/status/{user}")
def api_status(user: str):
    return status(user)

# Startup hook (rebuild from chain)
@router.on_event("startup")
def init_state():
    rebuild_state_from_chain()
