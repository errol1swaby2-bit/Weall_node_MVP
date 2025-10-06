#!/usr/bin/env python3
"""
Messaging API (WeAll Node)
---------------------------------------------------------
Peer-to-peer encrypted messaging between verified humans.

Features:
- Tier-2+ Proof-of-Humanity gating
- RSA encryption via executor crypto utils
- Optional IPFS storage for large payloads
- Read/unread tracking
- Future-ready for persistence and moderation
"""

import time, logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from weall_node.executor import encrypt_message, decrypt_message
from weall_node.weall_runtime.wallet import has_nft
from weall_node.weall_runtime.storage import get_client as get_ipfs_client
from weall_node.app_state import ledger

router = APIRouter(prefix="/messaging", tags=["messaging"])
logger = logging.getLogger("messaging")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# In-memory mailbox (temporary)
MAILBOX = {}  # user_id -> list[dict]


# -------------------------------
# Models
# -------------------------------
class MessageSend(BaseModel):
    from_user: str
    to_user: str
    text: str = Field(..., min_length=1, description="Plaintext message body")
    encrypt: bool = Field(default=True, description="Encrypt message with recipient's public key")


class MessageOut(BaseModel):
    id: int
    from_user: str
    timestamp: int
    ciphertext: str | None = None
    text: str | None = None
    ipfs_cid: str | None = None
    read: bool = False


# -------------------------------
# Internal Helpers
# -------------------------------
def _require_poh(user_id: str, level: int = 2):
    """Raise if user doesn't meet PoH tier requirement."""
    if not has_nft(user_id, "PoH", min_level=level):
        raise HTTPException(status_code=401, detail=f"PoH Tier-{level}+ required")


def _store_ipfs(data: str) -> str | None:
    """Attempt to store message text on IPFS; return CID or None."""
    try:
        ipfs = get_ipfs_client()
        if not ipfs:
            return None
        return ipfs.add_str(data)
    except Exception as e:
        logger.warning("IPFS storage failed: %s", e)
        return None


# -------------------------------
# Routes
# -------------------------------
@router.post("/send")
def send_message(msg: MessageSend):
    """
    Send a message from one verified user to another.
    - Encrypts using recipient's public key if available.
    - Stores in recipient's inbox.
    - Optionally uploads long messages to IPFS.
    """
    _require_poh(msg.from_user, level=2)
    _require_poh(msg.to_user, level=2)

    text = msg.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message body cannot be empty")

    timestamp = int(time.time())
    message_id = int(timestamp * 1000)
    ciphertext = None
    ipfs_cid = None

    # Encrypt message using recipient's key if available
    try:
        recipient = ledger.accounts.get(msg.to_user) if hasattr(ledger, "accounts") else None
        if msg.encrypt and recipient and "public_key" in recipient:
            ciphertext = encrypt_message(recipient["public_key"], text).hex()
        elif len(text) > 500:
            ipfs_cid = _store_ipfs(text)
    except Exception as e:
        logger.warning("Encryption failed for %s -> %s: %s", msg.from_user, msg.to_user, e)

    payload = {
        "id": message_id,
        "from_user": msg.from_user,
        "timestamp": timestamp,
        "text": text if not ciphertext else None,
        "ciphertext": ciphertext,
        "ipfs_cid": ipfs_cid,
        "read": False,
    }

    MAILBOX.setdefault(msg.to_user, []).append(payload)
    logger.info("Message %s sent from %s to %s", message_id, msg.from_user, msg.to_user)
    return {"ok": True, "message_id": message_id, "encrypted": bool(ciphertext), "ipfs": bool(ipfs_cid)}


@router.get("/inbox/{user_id}")
def get_inbox(user_id: str):
    """
    Retrieve decrypted inbox messages for a user.
    Messages stored with ciphertext are left encrypted;
    plaintext messages are returned directly.
    """
    _require_poh(user_id, level=2)
    inbox = MAILBOX.get(user_id, [])
    return {"ok": True, "user_id": user_id, "messages": inbox, "count": len(inbox)}


@router.post("/mark_read/{user_id}/{message_id}")
def mark_read(user_id: str, message_id: int):
    """Mark a message as read in the user's inbox."""
    inbox = MAILBOX.get(user_id)
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    for msg in inbox:
        if msg["id"] == message_id:
            msg["read"] = True
            logger.info("Message %s marked as read by %s", message_id, user_id)
            return {"ok": True, "message_id": message_id}

    raise HTTPException(status_code=404, detail="Message not found")


@router.get("/unread/{user_id}")
def get_unread(user_id: str):
    """List unread messages for a user."""
    _require_poh(user_id, level=2)
    unread = [m for m in MAILBOX.get(user_id, []) if not m.get("read")]
    return {"ok": True, "user_id": user_id, "unread_count": len(unread), "messages": unread}


@router.post("/decrypt/{user_id}/{message_id}")
def decrypt_message_for_user(user_id: str, message_id: int):
    """
    Attempt to decrypt a message if the user's private key is available.
    (Stub implementation; assumes executor manages keypairs.)
    """
    _require_poh(user_id, level=2)
    inbox = MAILBOX.get(user_id)
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox not found")

    for m in inbox:
        if m["id"] == message_id:
            if not m.get("ciphertext"):
                return {"ok": True, "text": m.get("text")}
            try:
                # Real decryption would pull user private key from executor.state
                plain = "[decryption simulated]"  # placeholder
                return {"ok": True, "text": plain}
            except Exception as e:
                logger.warning("Decryption failed: %s", e)
                raise HTTPException(status_code=500, detail="Decryption failed")

    raise HTTPException(status_code=404, detail="Message not found")
