from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app_state import poh, ledger
from weall_runtime.wallet import mint_nft

router = APIRouter(
    prefix="/verification",
    tags=["Verification (Unified PoH API)"]
)

class VerificationRequest(BaseModel):
    user_id: str
    level: int  # 1, 2, or 3

class EvidenceSubmission(BaseModel):
    user_id: str
    evidence_cid: str

@router.post("/request")
def request_verification(req: VerificationRequest):
    try:
        if req.level == 1:
            result = poh.verify_tier1(req.user_id)
            # Mint Tier1 NFT
            nft_id = f"poh-tier1-{req.user_id}"
            mint_nft(req.user_id, nft_id, "Tier1 guest verified")
            ledger.ledger.record_mint_event(req.user_id, nft_id)
            return {"status": "approved", "tier": 1, "nft": nft_id}

        elif req.level == 2:
            # Apply only, evidence will come later
            result = poh.apply_tier2(req.user_id, evidence="pending")
            return {"status": "pending", "tier": 2}

        elif req.level == 3:
            return {"status": "waiting_for_video", "tier": 3, "user": req.user_id}

        else:
            raise ValueError("Invalid level")

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
    try:
        # If evidence is a WebRTC recording → Tier3
        if data.evidence_cid.startswith("webrtc-"):
            result = poh.verify_tier3(data.user_id, data.evidence_cid)
            nft_id = f"poh-tier3-{data.user_id}"
            mint_nft(data.user_id, nft_id, "Tier3 live verified")
            ledger.ledger.record_mint_event(data.user_id, nft_id)
            return {"status": "approved", "tier": 3, "nft": nft_id}

        # Otherwise assume Tier2
        poh.apply_tier2(data.user_id, data.evidence_cid)
        result = poh.verify_tier2(data.user_id, approver="system", approve=True)
        if result.get("approved"):
            nft_id = f"poh-tier2-{data.user_id}"
            mint_nft(data.user_id, nft_id, "Tier2 async verified")
            ledger.ledger.record_mint_event(data.user_id, nft_id)
            return {"status": "approved", "tier": 2, "nft": nft_id}
        else:
            ledger.ledger.record_slash(data.user_id, 10, "tier2_failed")
            return {"status": "rejected", "tier": 2}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
