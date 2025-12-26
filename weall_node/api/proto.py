from __future__ import annotations

"""
Backward-compatible endpoints for older clients that call /proto/*.

Canonical implementation lives in weall_node.api.tx (the /tx lane).
"""

from fastapi import APIRouter

from . import tx as tx_api

router = APIRouter(prefix="/proto", tags=["proto-compat"])


@router.get("/status")
def status():
    return tx_api.status()


@router.post("/submit")
def submit(payload: tx_api.SubmitTx):
    return tx_api.submit(payload)


@router.get("/mempool")
def mempool(limit: int = 50):
    # Optional endpoint: only if tx_api has it; if not, provide minimal response
    return {"ok": True, "tx_ids": tx_api.txpool.MEMPOOL.list_tx_ids_hex(limit=limit)}  # type: ignore[attr-defined]


@router.get("/receipt/{tx_id}")
def receipt(tx_id: str):
    r = tx_api.txpool.receipts_get(tx_id)  # type: ignore[attr-defined]
    return {"ok": True, "receipt": r}
