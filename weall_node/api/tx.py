from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_runtime import txpool
from . import tx_sync

router = APIRouter(prefix="/tx", tags=["tx"])

_TX_ENABLED = os.getenv("WEALL_PROTO_TX", "0") == "1"


class SubmitTx(BaseModel):
    tx_b64: str = Field(..., description="base64-encoded TxEnvelope protobuf bytes")


@router.get("/status")
def status() -> Dict[str, Any]:
    return {
        "ok": True,
        "enabled": _TX_ENABLED,
        "chain_id": txpool.DOMAIN.chain_id,
        "schema_version": txpool.DOMAIN.schema_version,
        "mempool_size": txpool.MEMPOOL.size(),
    }


@router.post("/submit")
def submit(payload: SubmitTx) -> Dict[str, Any]:
    if not _TX_ENABLED:
        raise HTTPException(status_code=403, detail="tx lane disabled (set WEALL_PROTO_TX=1)")

    try:
        raw = base64.b64decode(payload.tx_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64")

    # Basic size limit (production MVP)
    max_bytes = int(os.getenv("WEALL_TX_MAX_BYTES", "262144"))  # 256KB default
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"tx too large (>{max_bytes} bytes)")

    try:
        item, is_new = txpool.ingest_raw_tx(raw, source="local")
    except Exception as e:
        # track rejected receipt (MVP)
        # if we can compute tx_id, it will exist already; otherwise just return error
        raise HTTPException(status_code=400, detail=f"invalid tx: {e}")

    # best-effort broadcast
    try:
        tx_sync.broadcast_tx(item.tx_id.hex(), item.raw, src=None)
    except Exception:
        pass

    return {
        "ok": True,
        "tx_id": item.tx_id.hex(),
        "tx_type": int(item.tx.tx_type),
        "mempool_size": txpool.MEMPOOL.size(),
        "new": bool(is_new),
        "ts": int(time.time()),
    }


@router.get("/mempool")
def mempool(limit: int = 50) -> Dict[str, Any]:
    if not _TX_ENABLED:
        raise HTTPException(status_code=403, detail="tx lane disabled (set WEALL_PROTO_TX=1)")
    return {"ok": True, "tx_ids": txpool.MEMPOOL.list_tx_ids_hex(limit=limit)}


@router.get("/{tx_id}")
def tx_status(tx_id: str) -> Dict[str, Any]:
    r = txpool.receipts_get(tx_id)
    if not r:
        return {"ok": True, "found": False}

    return {
        "ok": True,
        "found": True,
        "tx_id": r.tx_id,
        "status": r.status,
        "height": r.height,
        "block_id": r.block_id,
        "error": r.error,
        "ts": r.ts,
    }
