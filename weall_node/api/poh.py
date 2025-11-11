"""
Proof of Humanity (PoH) API + runtime-backed state management (v1.2)

Integrated with wallet.ensure_poh_badge()
to automatically mint tier NFTs recognized by validators.
"""

from __future__ import annotations
import random, string, time, logging
from typing import Dict, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from ..weall_executor import executor
from weall_node.weall_runtime.wallet import ensure_poh_badge  # ✅ integration

# -------------------------------
# In-memory state
# -------------------------------
STATE: Dict[str, dict] = {}  # user_id -> {tier, status, badges}
PENDING_EMAILS: Dict[str, dict] = {}  # user_id -> {email, code, timestamp}
SESSIONS: Dict[str, dict] = {}  # session_id -> session data

# -------------------------------
# Config
# -------------------------------
CODE_EXPIRY = 15 * 60
REQ_COOLDOWN = 60
logger = logging.getLogger("poh")

router = APIRouter(prefix="/poh", tags=["Proof of Humanity"])


# -------------------------------
# Helpers
# -------------------------------
def _send_email(to_addr: str, code: str):
    """Send real email if SMTP is configured; else log a mock."""
    subject = "WeAll Tier-1 verification code"
    body = f"""WeAll Tier-1 verification code

Your WeAll Tier-1 verification code is:
{code}

This code expires in {CODE_EXPIRY // 60} minutes.
If you did not request this, you can ignore this email.
"""
    try:
        from weall_node.utils.emailer import send_email

        send_email(to_addr, subject, body)
        logger.info("Sent Tier-1 code to %s", to_addr)
    except Exception as e:
        logger.warning(
            "SMTP send failed or not configured (%s). Falling back to log.", e
        )
        logger.info("[MOCK EMAIL] Sending Tier-1 code to %s: %s", to_addr, code)


def _generate_code(length=6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _events() -> List[dict]:
    return executor.ledger.setdefault("events", [])


def _record_event(evt: dict):
    evt = dict(evt)
    evt.setdefault("ts", int(time.time()))
    _events().append(evt)
    executor.save_state()


def _get_balance(user: str) -> float:
    try:
        return float(executor.ledger.get(user, 0.0))
    except Exception:
        return 0.0


def jurors_required(total_users: int) -> int:
    if total_users <= 1:
        return 0
    if total_users <= 2:
        return 1
    if total_users <= 6:
        return 2
    if total_users <= 20:
        return 3
    if total_users <= 40:
        return 5
    return 10


def _enqueue_tx(payload: dict):
    """Compatibility-safe way to stage a tx regardless of executor version."""
    try:
        executor.add_tx(payload)
    except AttributeError:
        executor.ledger.setdefault("mempool", []).append(payload)


# -------------------------------
# Chain replay
# -------------------------------
def rebuild_state_from_chain():
    """Rebuild PoH state from the append-only ledger."""
    global STATE
    STATE = {}

    for evt in _events():
        etype = evt.get("type")
        user = evt.get("user")
        if not user or not etype:
            continue
        rec = STATE.setdefault(user, {"tier": 0, "status": "unknown", "badges": []})
        if etype == "POH_TIER1":
            rec["tier"] = max(rec["tier"], 1)
            rec["status"] = "verified"
            if "Tier-1 Verified" not in rec["badges"]:
                rec["badges"].append("Tier-1 Verified")
        elif etype == "POH_TIER2_VERIFY" and evt.get("approved"):
            rec["tier"] = max(rec["tier"], 2)
            rec["status"] = "verified"
            if "Tier-2 Verified (NFT)" not in rec["badges"]:
                rec["badges"].append("Tier-2 Verified (NFT)")
        elif etype == "POH_TIER3_VERIFY" and evt.get("approved"):
            rec["tier"] = max(rec["tier"], 3)
            rec["status"] = "verified"
            if "Tier-3 Verified (NFT)" not in rec["badges"]:
                rec["badges"].append("Tier-3 Verified (NFT)")
    for user, data in STATE.items():
        data.setdefault("badges", [])


# -------------------------------
# Tier 1 Verification
# -------------------------------
def verify_tier1(user: str):
    """Register Tier-1 verification (email) and mint badge."""
    already = any(
        e.get("type") == "POH_TIER1" and e.get("user") == user for e in _events()
    )
    if already:
        return {"ok": True, "user": user, "tier": 1, "status": "already_registered"}

    _enqueue_tx({"poh": {"user": user, "tier": 1, "action": "verify"}})
    executor.mine_block()  # << takes no args
    _record_event({"type": "POH_TIER1", "user": user})

    # ✅ Mint badge via wallet
    badge = ensure_poh_badge(user, 1)
    logger.info(f"[PoH] Tier-1 badge minted for {user}: {badge['nft_id']}")

    STATE[user] = {
        "tier": 1,
        "status": "verified",
        "badges": ["Tier-1 Verified", badge["metadata"]["title"]],
    }
    return {"ok": True, "user": user, "tier": 1, "badge": badge}


# -------------------------------
# Tier 2 Verification
# -------------------------------
def apply_tier2(user: str, evidence: str):
    """Auto or juror approval of Tier-2 verification."""
    if STATE.get(user, {}).get("tier", 0) < 1:
        return {"ok": False, "error": "Tier-1 required first"}

    total_users = sum(isinstance(u, str) for u in STATE.keys())
    required = jurors_required(total_users)

    if required == 0:
        _enqueue_tx({"poh": {"user": user, "tier": 2, "action": "auto-approve"}})
        executor.mine_block()  # << fixed
        _record_event(
            {
                "type": "POH_TIER2_VERIFY",
                "user": user,
                "approved": True,
                "evidence": evidence,
            }
        )
        badge = ensure_poh_badge(user, 2)
        rebuild_state_from_chain()
        logger.info(f"[PoH] Tier-2 badge minted for {user}")
        return {"ok": True, "tier": 2, "status": "auto-approved", "badge": badge}

    jurors = [u for u, d in STATE.items() if d.get("tier", 0) >= 3]
    if len(jurors) < required:
        return {
            "ok": True,
            "status": "waiting_for_jurors",
            "available": len(jurors),
            "required": required,
        }

    selected = random.sample(jurors, required)
    session_id = f"{user}:tier2:{int(time.time())}"
    SESSIONS[session_id] = {
        "jurors": selected,
        "votes": {},
        "tier": 2,
        "status": "pending",
        "required": required,
    }
    return {"ok": True, "session": session_id, "jurors": selected, "required": required}


def verify_tier2(user: str, approver: str, approve: bool):
    if STATE.get(user, {}).get("tier", 0) < 1:
        return {"approved": False, "error": "Tier-1 required first"}
    if not approve:
        return {"approved": False}

    _enqueue_tx(
        {
            "poh": {
                "user": user,
                "tier": 2,
                "action": "juror-approve",
                "approver": approver,
            }
        }
    )
    executor.mine_block()  # << fixed
    _record_event(
        {
            "type": "POH_TIER2_VERIFY",
            "user": user,
            "approved": True,
            "approver": approver,
        }
    )
    badge = ensure_poh_badge(user, 2)
    rebuild_state_from_chain()
    logger.info(f"[PoH] Tier-2 juror approval complete for {user}")
    return {"approved": True, "badge": badge}


# -------------------------------
# Tier 3 Verification
# -------------------------------
def verify_tier3(user: str, video_proof: str):
    """Tier-3 verification with juror or auto-approval."""
    if STATE.get(user, {}).get("tier", 0) < 2:
        return {"ok": False, "error": "Tier-2 required first"}

    total_users = sum(isinstance(u, str) for u in STATE.keys())
    required = jurors_required(total_users)

    if required == 0:
        _enqueue_tx({"poh": {"user": user, "tier": 3, "action": "auto-approve"}})
        executor.mine_block()  # << fixed
        _record_event(
            {
                "type": "POH_TIER3_VERIFY",
                "user": user,
                "approved": True,
                "video_proof": video_proof,
            }
        )
        badge = ensure_poh_badge(user, 3)
        rebuild_state_from_chain()
        logger.info(f"[PoH] Tier-3 badge minted for {user}")
        return {"ok": True, "tier": 3, "status": "auto-approved", "badge": badge}

    jurors = [u for u, d in STATE.items() if d.get("tier", 0) >= 3]
    if len(jurors) < required:
        return {
            "ok": True,
            "status": "waiting_for_jurors",
            "available": len(jurors),
            "required": required,
        }

    selected = random.sample(jurors, required)
    session_id = f"{user}:tier3:{int(time.time())}"
    SESSIONS[session_id] = {
        "jurors": selected,
        "attestations": [],
        "tier": 3,
        "status": "pending",
        "required": required,
        "video_proof": video_proof,
        "user_id": user,
    }
    return {"ok": True, "session": session_id, "jurors": selected, "required": required}


def finalize_tier3(session_id: str):
    s = SESSIONS.get(session_id)
    if not s or s.get("status") != "pending":
        raise ValueError("Invalid or non-pending session.")
    approvals = sum(1 for a in s["attestations"] if a["decision"])
    s["status"] = "closed"
    user = s.get("user_id")

    if approvals >= s.get("required", 3):
        _enqueue_tx(
            {
                "poh": {
                    "user": user,
                    "tier": 3,
                    "action": "juror-approve",
                    "session": session_id,
                }
            }
        )
        executor.mine_block()  # << fixed
        _record_event(
            {
                "type": "POH_TIER3_VERIFY",
                "user": user,
                "approved": True,
                "session": session_id,
            }
        )
        badge = ensure_poh_badge(user, 3)
        rebuild_state_from_chain()
        logger.info(f"[PoH] Tier-3 juror approval complete for {user}")
        return {"approved": True, "tier": 3, "approvals": approvals, "badge": badge}

    return {"approved": False, "tier": 3, "approvals": approvals}


# -------------------------------
# Status
# -------------------------------
def status(user: str):
    data = STATE.get(user)
    if not data:
        return {"ok": False, "error": "User not found"}
    return {
        "ok": True,
        "user": user,
        "tier": data.get("tier"),
        "status": data.get("status", "unknown"),
        "badges": data.get("badges", []),
        "balance": _get_balance(user),
    }


# -------------------------------
# Models + Routes
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


@router.post("/request-tier1")
def api_request_tier1(req: Tier1Request, background: BackgroundTasks):
    now = time.time()
    if (p := PENDING_EMAILS.get(req.user)) and now - p["timestamp"] < REQ_COOLDOWN:
        raise HTTPException(status_code=429, detail="Cooldown active — try again soon")
    code = _generate_code()
    PENDING_EMAILS[req.user] = {"email": req.email, "code": code, "timestamp": now}
    background.add_task(_send_email, req.email, code)
    return {
        "ok": True,
        "message": f"Verification code sent to {req.email} (via SMTP/log)",
    }


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
def api_apply_tier2(req: Tier2Request):
    return apply_tier2(req.user, req.evidence)


@router.post("/tier3")
def api_verify_tier3(req: Tier3Request):
    return verify_tier3(req.user, req.video_proof)


@router.get("/status/{user}")
def api_status(user: str):
    return status(user)


@router.on_event("startup")
def init_state():
    rebuild_state_from_chain()
