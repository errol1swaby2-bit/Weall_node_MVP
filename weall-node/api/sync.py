# api/sync.py
from fastapi import APIRouter, HTTPException, Request, Query
import app_state  # instead of "from app_state import ledger, node"

router = APIRouter()

@router.get("/snapshot")
def get_snapshot():
    """Returns the current ledger snapshot."""
    try:
        return app_state.ledger.snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get snapshot: {e}")

@router.post("/push")
async def push_snapshot(request: Request):
    """Receive a snapshot from a peer and merge it."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        app_state.ledger.accounts.update(data.get("accounts", {}))
        for pool, members in data.get("pools", {}).items():
            app_state.ledger.pools[pool].update(members)

        if hasattr(app_state.ledger, "eligibility"):
            app_state.ledger.eligibility.update(data.get("eligibility", {}))
        if hasattr(app_state.ledger, "applications"):
            app_state.ledger.applications.update(data.get("applications", {}))
        if hasattr(app_state.ledger, "verifications"):
            app_state.ledger.verifications.update(data.get("verifications", {}))
        if hasattr(app_state.ledger, "proposals"):
            app_state.ledger.proposals.update(data.get("proposals", {}))

        if hasattr(app_state.ledger, "_save"):
            app_state.ledger._save()

        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to merge snapshot: {e}")

@router.post("/register_peer")
def register_peer(peer_url: str = Query(...)):
    """Register a new peer URL with this node."""
    try:
        peers = app_state.node.register_peer(peer_url)
        return {"ok": True, "peers": peers}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/peers")
def list_peers():
    """Return list of known peers."""
    return {"peers": app_state.node.peers}
