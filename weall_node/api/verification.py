#!/usr/bin/env python3
"""
Verification API (Unified PoH Interface)
---------------------------------------------------------
High-level orchestration for Proof-of-Humanity verification.
Bridges UI/API requests to core PoH logic without duplicating minting.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from weall_node.api import poh
from weall_node.weall_runtime.wallet import has_nft

router = APIRouter(prefix="/verification", tags=["verification"])
logger = logging.getLogger("verification")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# -------------------------------
# Request Models
# -------------------------------
class VerificationRequest(BaseModel):
    user_id: str
    level: int  # 1, 2, or 3


class EvidenceSubmission(BaseModel):
    user_id: str
    evidence_cid: str


class CreateTier3Session(BaseModel):
    user_id: str
    jurors: list[str]


class Tier3Attestation(BaseModel):
    session_id: str
    juror_id: str
    decision: bool


class Tier3Finalize(BaseModel):
    session_id: str


# -------------------------------
# Helpers
# -------------------------------
def _require_tier(user_id: str, min_level: int):
    """Ensure a user holds at least the specified PoH NFT level."""
    if not has_nft(user_id, "PoH", min_level=min_level):
        raise HTTPException(status_code=401, detail=f"PoH Tier-{min_level}+ required")


# -------------------------------
# Routes
# -------------------------------
@router.post("/request")
def request_verification(req: VerificationRequest):
    """
    Request verification at a given PoH tier.
    Tier 1: returns instructions for email flow.
    Tier 2: initiates async juror flow.
    Tier 3: signals readiness for live video proof.
    """
    try:
        if req.level == 1:
            return {
                "ok": True,
                "status": "use_poh_tier1_flow",
                "hint": "POST /poh/request-tier1 then /poh/verify-tier1 with the code from email logs."
            }
        elif req.level == 2:
            out = poh.apply_tier2(req.user_id, evidence="pending")
            logger.info("Tier-2 verification requested by %s", req.user_id)
            return {"ok": True, **out}
        elif req.level == 3:
            logger.info("Tier-3 verification requested by %s", req.user_id)
            return {"ok": True, "status": "waiting_for_video", "tier": 3, "user": req.user_id}
        else:
            raise ValueError("Invalid level (must be 1, 2, or 3)")
    except Exception as e:
        logger.exception("Verification request failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
def verification_status(user_id: str):
    """Return the user’s PoH verification status."""
    try:
        result = poh.status(user_id)
        logger.info("Verification status check for %s", user_id)
        return {"ok": True, **result}
    except Exception as e:
        logger.exception("Status check failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submit-evidence")
def submit_evidence(data: EvidenceSubmission):
    """
    Handle user evidence submissions.
    - Tier 2: auto-verifies with juror system.
    - Tier 3: defers to live-session workflow.
    """
    _require_tier(data.user_id, 2)

    try:
        if data.evidence_cid.startswith("webrtc-"):
            logger.info("Tier-3 evidence submitted by %s", data.user_id)
            return {
                "ok": True,
                "status": "session_required",
                "tier": 3,
                "hint": "Use /verification/tier3/create-session to begin juror attestation."
            }

        # Default to Tier 2 path
        poh.apply_tier2(data.user_id, data.evidence_cid)
        result = poh.verify_tier2(data.user_id, approver="system", approve=True)
        logger.info("Tier-2 evidence auto-approved for %s", data.user_id)
        return {
            "ok": True,
            "status": "approved" if result.get("approved") else "rejected",
            "tier": 2,
            **({"block": result.get("block"), "nft": result.get("nft")} if result.get("approved") else {})
        }
    except Exception as e:
        logger.exception("Evidence submission failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tier3/create-session")
def tier3_create_session(data: CreateTier3Session):
    """Create a Tier-3 juror session."""
    _require_tier(data.user_id, 3)
    try:
        out = poh.create_tier3_session(data.user_id, data.jurors)
        logger.info("Tier-3 session created by %s with %d jurors", data.user_id, len(data.jurors))
        return {"ok": True, "status": "created", **out}
    except Exception as e:
        logger.exception("Tier3 session creation failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tier3/attest")
def tier3_attest(data: Tier3Attestation):
    """Juror attests a Tier-3 verification session."""
    _require_tier(data.juror_id, 3)
    try:
        out = poh.juror_attest(data.session_id, data.juror_id, data.decision)
        logger.info("Juror %s attested on session %s (decision=%s)", data.juror_id, data.session_id, data.decision)
        return {"ok": True, **out}
    except Exception as e:
        logger.exception("Tier3 attestation failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tier3/finalize")
def tier3_finalize(data: Tier3Finalize):
    """Finalize a Tier-3 session (minting handled in poh.finalize_tier3)."""
    try:
        out = poh.finalize_tier3(data.session_id)
        logger.info("Tier-3 session finalized: %s", data.session_id)
        return {"ok": True, **out}
    except Exception as e:
        logger.exception("Tier3 finalization failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
