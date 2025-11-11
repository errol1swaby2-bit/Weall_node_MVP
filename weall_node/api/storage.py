"""
weall_node/api/storage.py
--------------------------------------------------
Simple IPFS operator endpoints for WeAll Node v1.1.
"""

from fastapi import APIRouter, HTTPException
from ..weall_executor import executor

router = APIRouter()


@router.get("/health")
def get_ipfs_health():
    """Return the current IPFS connection status."""
    if not executor.ipfs:
        raise HTTPException(status_code=503, detail="IPFS manager not available")
    return executor.ipfs.health()


@router.post("/pin/{cid}")
def pin_cid(cid: str):
    """Pin a CID to the operator's IPFS node."""
    if not executor.ipfs:
        raise HTTPException(status_code=503, detail="IPFS manager not available")
    ok = executor.ipfs.pin_cid(cid)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to pin CID")
    return {"ok": True, "cid": cid}


@router.post("/unpin/{cid}")
def unpin_cid(cid: str):
    """Unpin a CID from the operator's IPFS node."""
    if not executor.ipfs:
        raise HTTPException(status_code=503, detail="IPFS manager not available")
    ok = executor.ipfs.unpin_cid(cid)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to unpin CID")
    return {"ok": True, "cid": cid}
