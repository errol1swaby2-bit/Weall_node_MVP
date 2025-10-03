from fastapi import APIRouter, HTTPException
from ..weall_runtime.storage import get_client

router = APIRouter(prefix="/pin", tags=["pinning"])

@router.post("/add")
async def pin_add(cid: str):
    ipfs = get_client()
    if not ipfs:
        raise HTTPException(503, "IPFS client not ready")
    ipfs.pin_add(cid)
    return {"pinned": cid}
