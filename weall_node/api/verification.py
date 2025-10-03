from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ✅ Thin wrapper around blockchain-backed PoH (no minting here!)
from weall_node.api import poh

router = APIRouter(
    prefix="/verification",
    tags=["Verification (Unified PoH API)"]
)

# -------------------------------
# Request/Submission Models
# -------------------------------
class VerificationRequest(BaseModel):
    user_id: str
    level: int  # 1, 2, or 3

class EvidenceSubmission(BaseModel):
    user_id: str
    evidence_cid: str

class CreateTier3Session(BaseModel):
    user_id: str
    jurors: list[str]   # MVP: require >=3 jurors

class Tier3Attestation(BaseModel):
    session_id: str
    juror_id: str
    decision: bool

class Tier3Finalize(BaseModel):
    session_id: str


# -------------------------------
# Routes (no double-minting)
# -------------------------------
@router.post("/request")
def request_verification(req: VerificationRequest):
    """
    Level 1 has a two-step flow (email -> code), so we DO NOT auto-verify here.
    Return guidance to use /poh/request-tier1 and /poh/verify-tier1.
    Level 2 and 3 return thin orchestration responses.
    """
    try:
        if req.level == 1:
            return {
                "status": "use_poh_tier1_flow",
                "hint": "POST /poh/request-tier1 then /poh/verify-tier1 with the code from email logs."
            }

        elif req.level == 2:
            out = poh.apply_tier2(req.user_id, evidence="pending")
            return out

        elif req.level == 3:
            return {"status": "waiting_for_video", "tier": 3, "user": req.user_id}

        else:
            raise ValueError("Invalid level (must be 1, 2, or 3)")

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
def verification_status(user_id: str):
    try:
        return poh.status(user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/submit-evidence")
def submit_evidence(data: EvidenceSubmission):
    """
    If evidence looks like a WebRTC recording → Tier 3 path (session/attest/finalize).
    Otherwise → Tier 2 auto verification via poh.verify_tier2 (no double-mint here).
    """
    try:
        if data.evidence_cid.startswith("webrtc-"):
            return {
                "status": "session_required",
                "tier": 3,
                "hint": "Create Tier3 session and collect juror attestations"
            }

        # Default to Tier 2
        poh.apply_tier2(data.user_id, data.evidence_cid)
        result = poh.verify_tier2(data.user_id, approver="system", approve=True)
        return {
            "status": "approved" if result.get("approved") else "rejected",
            "tier": 2,
            **({"block": result.get("block"), "nft": result.get("nft")} if result.get("approved") else {})
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tier3/create-session")
def tier3_create_session(data: CreateTier3Session):
    try:
        out = poh.create_tier3_session(data.user_id, data.jurors)
        return {"status": "created", **out}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tier3/attest")
def tier3_attest(data: Tier3Attestation):
    try:
        out = poh.juror_attest(data.session_id, data.juror_id, data.decision)
        return {"ok": True, **out}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tier3/finalize")
def tier3_finalize(data: Tier3Finalize):
    """
    Finalization + minting are performed inside poh.finalize_tier3, so we just forward the result.
    """
    try:
        out = poh.finalize_tier3(data.session_id)
        return out
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
