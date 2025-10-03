# api/governance.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from weall_node.app_state import governance

router = APIRouter()

class ProposalCreate(BaseModel):
    user: str
    title: str
    description: str
    pallet_reference: str

class VoteCast(BaseModel):
    user: str
    proposal_id: str
    vote: str

@router.post("/propose")
def propose(data: ProposalCreate):
    try:
        return governance.propose(data.user, data.title, data.description, data.pallet_reference)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/vote")
def vote(data: VoteCast):
    try:
        return governance.vote(data.user, data.proposal_id, data.vote)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/proposals")
def list_proposals():
    return governance.list_proposals()
