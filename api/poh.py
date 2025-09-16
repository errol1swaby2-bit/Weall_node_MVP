from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app_state import poh

router = APIRouter(
    prefix="/poh",
    tags=["Proof of Humanity"]
)

class ApplyTier2(BaseModel):
    user: str
    evidence: str

class VerifyTier2(BaseModel):
    user: str
    approver: str
    approve: bool

class VerifyTier3(BaseModel):
    user: str
    video_proof: str

@router.post("/tier1/{user}")
def verify_tier1(user: str):
    return poh.verify_tier1(user)

@router.post("/tier2/apply")
def apply_tier2(data: ApplyTier2):
    return poh.apply_tier2(data.user, data.evidence)

@router.post("/tier2/verify")
def verify_tier2(data: VerifyTier2):
    return poh.verify_tier2(data.user, data.approver, data.approve)

@router.post("/tier3/verify")
def verify_tier3(data: VerifyTier3):
    return poh.verify_tier3(data.user, data.video_proof)

@router.get("/status/{user}")
def get_status(user: str):
    return poh.status(user)
