"""
weall_node/api/messaging.py
--------------------------------------------------
Encrypted peer & local messaging for WeAll Node v1.1
- AES-GCM encryption/decryption (from executor helpers)
- Local inbox persistence
- Automatic broadcast via IPFS pubsub (sync layer)
"""

import time
from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any
from ..weall_executor import executor
from ..crypto_utils import encrypt_message, decrypt_message

# Optional pubsub integration
try:
    from ..p2p.sync_manager import SyncManager

    sync_mgr = SyncManager()
    sync_mgr.connect()
except Exception as e:
    print(f"[WARN] SyncManager unavailable: {e}")
    sync_mgr = None

router = APIRouter()

# -----------------------------------------------------------
# In-memory message store (simulate local DB / DHT cache)
# -----------------------------------------------------------
MESSAGES: List[Dict[str, Any]] = []


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------
def _store_message(sender: str, recipient: str, cipher: str) -> Dict[str, Any]:
    msg = {
        "sender": sender,
        "recipient": recipient,
        "cipher": cipher,
        "timestamp": int(time.time()),
        "block_height": executor.block_height,
        "epoch": executor.epoch,
    }
    MESSAGES.append(msg)
    executor.save_state()
    return msg


def _broadcast_message(msg: Dict[str, Any]) -> None:
    """Send encrypted message to peers via IPFS pubsub."""
    if not sync_mgr or not sync_mgr.client:
        print("[WARN] sync_mgr not connected; skipping broadcast")
        return
    payload = {
        "type": "message",
        "msg": msg,
        "sender_pubkey": getattr(executor, "_pubkey_b64", None),
    }
    try:
        sync_mgr.publish(payload)
    except Exception as e:
        print(f"[WARN] broadcast failed: {e}")


# -----------------------------------------------------------
# API Routes
# -----------------------------------------------------------
@router.post("/send")
def send_message(sender: str, recipient: str, content: str, key: str = "local"):
    """
    Encrypt and store message locally, then broadcast to peers.
    `key` may be a shared secret or conversation-specific key.
    """
    cipher = encrypt_message(content, key)
    msg = _store_message(sender, recipient, cipher)
    _broadcast_message(msg)
    return {"ok": True, "message": msg}


@router.get("/inbox/{user_id}")
def get_inbox(user_id: str, key: str = "local"):
    """
    Retrieve & decrypt all messages for a user.
    The same key used for encryption must be provided.
    """
    inbox = [m for m in MESSAGES if m["recipient"] == user_id]
    if not inbox:
        raise HTTPException(status_code=404, detail="No messages for user")
    readable = []
    for m in inbox:
        try:
            text = decrypt_message(m["cipher"], key)
        except Exception:
            text = "<decryption-failed>"
        readable.append(
            {
                "from": m["sender"],
                "timestamp": m["timestamp"],
                "block_height": m["block_height"],
                "message": text,
            }
        )
    return {"ok": True, "count": len(readable), "messages": readable}


@router.get("/sent/{user_id}")
def get_sent(user_id: str):
    """Return all messages sent by a given user (ciphertext only)."""
    sent = [m for m in MESSAGES if m["sender"] == user_id]
    if not sent:
        raise HTTPException(status_code=404, detail="No sent messages for user")
    return {"ok": True, "count": len(sent), "messages": sent}


@router.get("/raw")
def get_raw_messages():
    """Debug: view raw encrypted message payloads."""
    return {"ok": True, "messages": MESSAGES}


@router.delete("/clear")
def clear_messages():
    """Clear local message store (testing only)."""
    MESSAGES.clear()
    return {"ok": True, "cleared": True}


# -----------------------------------------------------------
# Incoming pubsub hook
# -----------------------------------------------------------
def handle_incoming_pubsub(msg: Dict[str, Any]):
    """Handle received pubsub messages (called by sync listener)."""
    if msg.get("type") != "message":
        return
    payload = msg.get("msg")
    if not isinstance(payload, dict):
        return
    # Avoid duplicates (same sender+timestamp)
    exists = any(
        p["sender"] == payload.get("sender")
        and p["timestamp"] == payload.get("timestamp")
        for p in MESSAGES
    )
    if not exists:
        MESSAGES.append(payload)
        print(
            f"[SYNC] Received message from {payload.get('sender')} to {payload.get('recipient')}"
        )


# Attach callback if sync manager is alive
if sync_mgr:
    sync_mgr.start_listener(handle_incoming_pubsub)
