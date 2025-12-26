from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter

from ..p2p.sync_manager import SyncManager
from ..weall_runtime import txpool

router = APIRouter(prefix="/txsync", tags=["txsync"])

# Dedicated topic for tx gossip
tx_sync_mgr = SyncManager(topic="weall-tx")


def _handle_tx_pubsub(payload: Dict[str, Any]) -> None:
    """
    Expected payload:
      { "type": "tx", "tx_id": "<hex>", "raw_b64": "<base64>", "ts": <int>, "src": "<node_id>" }
    """
    if payload.get("type") != "tx":
        return

    tx_id = payload.get("tx_id")
    raw_b64 = payload.get("raw_b64")
    if not isinstance(tx_id, str) or not isinstance(raw_b64, str):
        return

    # loop prevention
    if txpool.SEEN.has(tx_id):
        return

    try:
        raw = txpool.decode_b64(raw_b64)
        txpool.ingest_raw_tx(raw, source="pubsub")
    except Exception:
        # keep gossip best-effort and silent
        return


# Start listener as soon as module is imported (best-effort)
try:  # pragma: no cover
    if tx_sync_mgr.connect():
        tx_sync_mgr.start_listener(_handle_tx_pubsub)
except Exception:
    pass


def broadcast_tx(tx_id_hex: str, raw: bytes, src: Optional[str] = None) -> bool:
    """
    Best-effort gossip.
    """
    if txpool.SEEN.has(tx_id_hex):
        # already seen/broadcasted recently
        return False

    txpool.SEEN.mark(tx_id_hex)

    if not tx_sync_mgr.connect():
        return False

    payload = {
        "type": "tx",
        "tx_id": tx_id_hex,
        "raw_b64": txpool.encode_b64(raw),
        "ts": int(time.time()),
        "src": src,
    }
    return bool(tx_sync_mgr.publish(payload))


@router.get("/status")
def status() -> Dict[str, Any]:
    s = tx_sync_mgr.status()
    s.update({
        "ok": True,
        "topic": "weall-tx",
        "mempool_size": txpool.MEMPOOL.size(),
    })
    return s
