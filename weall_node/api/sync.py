"""
weall_node/api/sync.py
--------------------------------------------------
P2P sync API for WeAll Node v1.1.
Manages peer registration and publishes block / epoch events via IPFS pubsub.
"""

import time
from fastapi import APIRouter, HTTPException
from ..weall_executor import executor
from ..p2p.sync_manager import SyncManager

router = APIRouter()
sync_mgr = SyncManager()

# Connect on module import
sync_mgr.connect()


# Background listener callback
def handle_incoming(msg):
    """Called whenever a pubsub message arrives."""
    if msg.get("type") == "block":
        remote_height = msg.get("height", 0)
        if remote_height > executor.block_height:
            print(
                f"[SYNC] Remote block #{remote_height} seen; local={executor.block_height}"
            )
    elif msg.get("type") == "epoch":
        print(f"[SYNC] Remote epoch {msg.get('epoch')} broadcast")


sync_mgr.start_listener(handle_incoming)

# -----------------------------------------------------------
# Routes
# -----------------------------------------------------------


@router.get("/status")
def sync_status():
    """Return local node sync status."""
    return {
        "ok": True,
        "block_height": executor.block_height,
        "epoch": executor.epoch,
        "ipfs_connected": bool(sync_mgr.client),
    }


@router.post("/broadcast/block")
def broadcast_block():
    """Publish current block height to the network."""
    if not sync_mgr.client and not sync_mgr.connect():
        raise HTTPException(status_code=503, detail="Sync manager not connected")
    payload = {
        "type": "block",
        "height": executor.block_height,
        "timestamp": int(time.time()),
    }
    sync_mgr.publish(payload)
    return {"ok": True, "broadcast": payload}


@router.post("/broadcast/epoch")
def broadcast_epoch():
    """Publish current epoch to the network."""
    if not sync_mgr.client and not sync_mgr.connect():
        raise HTTPException(status_code=503, detail="Sync manager not connected")
    payload = {
        "type": "epoch",
        "epoch": executor.epoch,
        "timestamp": int(time.time()),
    }
    sync_mgr.publish(payload)
    return {"ok": True, "broadcast": payload}
