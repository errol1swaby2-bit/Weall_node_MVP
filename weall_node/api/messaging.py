"""
weall_node/api/messaging.py
--------------------------------------------------
Minimal P2P-aware messaging API for WeAll Node (Genesis).

Goals:
- Let clients send messages between user IDs.
- Store messages in executor.ledger["messaging"]["messages"].
- Broadcast messages over IPFS pubsub for other nodes to ingest.
- Provide inbox/sent views for the web client.

Encryption model (Genesis):
- The server does NOT encrypt/decrypt; it simply stores payloads.
- Clients may send either:
    - plaintext `content`, or
    - `ciphertext` + `nonce` (client-side encryption).
- Both forms are stored; it is up to clients to decide what to display.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..p2p.sync_manager import SyncManager

router = APIRouter(prefix="/messaging", tags=["messaging"])

# Dedicated pubsub manager for messaging (separate from /sync)
msg_sync_mgr = SyncManager(topic="weall-sync")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    """
    Payload for sending a new message.

    sender:    user identifier (e.g. email, handle, or user_id)
    recipient: target user identifier
    content:   optional plaintext message
    ciphertext / nonce: optional encrypted form (client-side crypto)
    meta:      free-form metadata (thread ids, tags, etc.)
    """

    sender: str = Field(..., max_length=320, description="Sender user identifier")
    recipient: str = Field(..., max_length=320, description="Recipient user identifier")
    content: str = Field(
        "",
        max_length=4000,
        description="Plaintext content (optional when ciphertext is provided).",
    )
    ciphertext: Optional[str] = Field(
        None,
        description="Client-side encrypted message bytes (hex/base64/etc.).",
    )
    nonce: Optional[str] = Field(
        None,
        description="Associated nonce/IV for ciphertext (if applicable).",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form metadata (thread_id, tags, etc.).",
    )

    @property
    def is_empty(self) -> bool:
        return not self.content and not self.ciphertext


class MessageOut(BaseModel):
    """
    Public representation of a stored message.
    """

    id: str
    sender: str
    recipient: str
    created_at: int
    content: str = ""
    ciphertext: Optional[str] = None
    nonce: Optional[str] = None
    meta: Dict[str, Any]


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------


def _get_store() -> List[Dict[str, Any]]:
    """
    Return the message list from executor.ledger, creating structures as needed.
    """
    ledger = executor.ledger
    messaging = ledger.setdefault("messaging", {})
    messages = messaging.setdefault("messages", [])
    # Ensure list type
    if not isinstance(messages, list):
        messaging["messages"] = []
        messages = messaging["messages"]
    return messages


def _save_store() -> None:
    """
    Best-effort persistence of the ledger after mutations.
    """
    try:
        executor.save_state()
    except Exception:
        # Non-fatal in Genesis
        pass


def _normalize_message(raw: Dict[str, Any]) -> MessageOut:
    """
    Convert a raw dict from the ledger into a MessageOut model.
    """
    return MessageOut(
        id=str(raw.get("id", "")),
        sender=str(raw.get("sender", "")),
        recipient=str(raw.get("recipient", "")),
        created_at=int(raw.get("created_at", 0)),
        content=str(raw.get("content", "")),
        ciphertext=raw.get("ciphertext"),
        nonce=raw.get("nonce"),
        meta=raw.get("meta") or {},
    )


def _ingest_message(raw: Dict[str, Any]) -> bool:
    """
    Insert a message into the local store if it's not already present.

    Returns True if the message was added, False if it was ignored as a duplicate
    or invalid.
    """
    if not isinstance(raw, dict):
        return False

    msg_id = raw.get("id")
    if not msg_id:
        return False

    messages = _get_store()

    # De-duplicate by id
    for existing in messages:
        if existing.get("id") == msg_id:
            return False

    messages.append(raw)
    _save_store()
    return True


# ---------------------------------------------------------------------------
# Pubsub integration
# ---------------------------------------------------------------------------


def _handle_pubsub_message(payload: Dict[str, Any]) -> None:
    """
    Handle incoming pubsub messages of type "message".
    """
    if not isinstance(payload, dict):
        return
    if payload.get("type") != "message":
        # This manager only cares about "message" events; other types belong to /sync.
        return

    raw = payload.get("message")
    if not isinstance(raw, dict):
        return

    added = _ingest_message(raw)
    if added:
        print(
            f"[MESSAGING] Ingested remote message id={raw.get('id')} "
            f"from={raw.get('sender')} to={raw.get('recipient')}"
        )


# Attach listener on import if IPFS is reachable
try:
    if msg_sync_mgr.connect():
        msg_sync_mgr.start_listener(_handle_pubsub_message)
except Exception as e:
    print(f"[WARN] messaging sync listener not started: {e}")


def _publish_message(raw: Dict[str, Any]) -> None:
    """
    Broadcast a message over pubsub. Fire-and-forget; errors are logged but not raised.
    """
    payload: Dict[str, Any] = {
        "type": "message",
        "message": raw,
        "timestamp": int(time.time()),
    }
    try:
        msg_sync_mgr.publish(payload)
    except Exception as e:
        print(f"[WARN] messaging pubsub publish failed: {e}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/send", response_model=MessageOut)
def send_message(payload: MessageCreate):
    """
    Send a message from sender → recipient.

    Stores the message locally and broadcasts it via P2P pubsub so other nodes
    (including those hosting the recipient's home shard) can ingest it.
    """
    if payload.is_empty:
        raise HTTPException(
            status_code=400,
            detail="Either content or ciphertext must be provided",
        )

    now = int(time.time())
    msg_id = secrets.token_hex(16)

    raw: Dict[str, Any] = {
        "id": msg_id,
        "sender": payload.sender,
        "recipient": payload.recipient,
        "created_at": now,
        "content": payload.content or "",
        "ciphertext": payload.ciphertext,
        "nonce": payload.nonce,
        "meta": dict(payload.meta or {}),
    }

    # Insert into local store
    _ingest_message(raw)

    # Broadcast to peers (best-effort)
    _publish_message(raw)

    return _normalize_message(raw)


@router.get("/inbox/{user_id}", response_model=List[MessageOut])
def get_inbox(user_id: str):
    """
    Return all messages addressed TO the given user_id, newest first.

    This is the endpoint currently called by the web client for the inbox view.
    """
    messages = _get_store()
    filtered = [
        _normalize_message(m) for m in messages if str(m.get("recipient")) == user_id
    ]
    filtered.sort(key=lambda m: m.created_at, reverse=True)
    return filtered


@router.get("/sent/{user_id}", response_model=List[MessageOut])
def get_sent(user_id: str):
    """
    Return all messages sent FROM the given user_id, newest first.

    This is the endpoint currently called by the web client for the sent view.
    """
    messages = _get_store()
    filtered = [
        _normalize_message(m) for m in messages if str(m.get("sender")) == user_id
    ]
    filtered.sort(key=lambda m: m.created_at, reverse=True)
    return filtered
