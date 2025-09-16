# api/verification.py
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from weall_runtime.poh import juror_submit_vote
from weall_runtime.ledger import get_application

router = APIRouter()

class JurorVoteReq(BaseModel):
    app_id: str
    juror_pub: str
    vote: str  # "approve" or "reject"
    signature_b64: str  # Ed25519 signature of message "app_id:vote"

@router.post("/juror_vote")
async def juror_vote(req: JurorVoteReq, request: Request):
    # Basic validation: application exists and juror assigned
    app_rec = get_application(req.app_id)
    if not app_rec:
        raise HTTPException(status_code=404, detail="application not found")
    jurors = []
    try:
        jurors = json.loads(app_rec.jurors or "[]")
    except Exception:
        jurors = []
    if req.juror_pub not in jurors:
        raise HTTPException(status_code=403, detail="not assigned juror")
    # verify signature (done inside juror_submit_vote)
    res = juror_submit_vote(req.app_id, req.juror_pub, req.vote, req.signature_b64)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "vote failed"))
    return res
