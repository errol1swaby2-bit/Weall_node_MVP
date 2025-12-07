"""
weall_node/api/sync.py
--------------------------------------------------
P2P sync API for WeAll Node v1.1.
Manages peer registration and publishes block / epoch events via IPFS pubsub.

All incoming blocks from the network are gated by Proof-of-Humanity (PoH):
- Only blocks whose `proposer` has a PoH tier >= MIN_TIER are applied.
- Rejected blocks are logged under executor.ledger['sync']['rejections'].
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..p2p.sync_manager import SyncManager
from ..core.poh_gate import (
    MIN_TIER,
    get_poh_tier,
    log_block_rejection,
    get_rejection_stats,
)

router = APIRouter(prefix="/sync", tags=["sync"])

# Single shared SyncManager for the node
sync_mgr = SyncManager(topic="weall-sync")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class BlockEnvelope(BaseModel):
    """Block broadcast payload.

    We keep the envelope minimal so different block formats can evolve
    without changing the sync API: the `block` field is passed directly
    into the executor after gating + sanity checks.
    """

    block: Dict[str, Any] = Field(..., description="Block object to broadcast")
    src: Optional[str] = Field(
        None,
        description="Optional peer identifier of the broadcaster (for debugging)",
    )


class EpochEnvelope(BaseModel):
    """Epoch broadcast payload (rarely used directly by clients)."""

    epoch: int
    height: Optional[int] = None
    block_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _apply_block_from_network(block: Dict[str, Any]) -> bool:
    """Apply a block received from the network with PoH gating.

    This is intentionally conservative:
    - require a proposer id
    - require proposer PoH tier >= MIN_TIER
    - require height to be the next height after the local tip
    - require prev_block_id to match local tip (if any)

    We deliberately keep hash/signature checks minimal for now and
    rely on PoH + honest-majority assumptions in the Genesis network.
    """
    proposer = block.get("proposer") or block.get("proposer_id")
    if not proposer:
        log_block_rejection(block, "missing_proposer")
        return False

    tier = get_poh_tier(proposer)
    if tier < MIN_TIER:
        log_block_rejection(block, f"poh_tier_{tier}_insufficient")
        print(f"[SYNC] Rejected block from {proposer}: PoH tier {tier} < {MIN_TIER}")
        return False

    # Check height continuity
    ledger = executor.ledger  # type: ignore[attr-defined]
    chain = ledger.setdefault("chain", [])
    local_height = len(chain)
    bh = int(block.get("height", -1))
    if bh != local_height:
        log_block_rejection(block, f"height_mismatch:{bh}!={local_height}")
        print(
            f"[SYNC] Rejected block from {proposer}: height {bh} != local {local_height}"
        )
        return False

    # Check prev_block_id matches local tip (if any)
    prev_block_id = block.get("prev_block_id")
    if chain:
        tip_id = chain[-1].get("block_id") or chain[-1].get("hash")
        if prev_block_id != tip_id:
            log_block_rejection(
                block,
                f"prev_block_mismatch:{prev_block_id}!={tip_id}",
            )
            print(
                f"[SYNC] Rejected block from {proposer}: prev_block_id {prev_block_id} != local tip {tip_id}"
            )
            return False
    else:
        # For a genesis block we accept prev_block_id in {None, "", "0"}
        if prev_block_id not in (None, "", "0"):
            log_block_rejection(block, "non_genesis_with_empty_chain")
            return False

    # At this point we tentatively trust the block and apply it.
    try:
        # Apply all txs to the local ledger
        executor._apply_block(block)  # type: ignore[attr-defined]
        chain.append(block)
        # Keep basic height tracking consistent
        executor.current_block_height = len(chain)  # type: ignore[attr-defined]
        executor.save_state()  # type: ignore[attr-defined]
        print(
            f"[SYNC] Accepted block height={bh} from {proposer} (tier={tier}) id={block.get('block_id')}"
        )
        return True
    except Exception as e:  # pragma: no cover - defensive
        log_block_rejection(block, f"apply_failed:{e}")
        print(f"[SYNC] Failed to apply block from {proposer}: {e}")
        return False


def _handle_pubsub_message(payload: Dict[str, Any]) -> None:
    """Callback for SyncManager pubsub listener."""
    msg_type = payload.get("type")
    if msg_type == "block":
        block = payload.get("block") or {}
        if not isinstance(block, dict):
            print("[SYNC] Ignoring malformed block payload from pubsub")
            return
        _apply_block_from_network(block)
    elif msg_type == "epoch":
        # Epoch gossip is advisory only right now; we don't mutate state.
        return
    else:
        # Future expansion: pings, diagnostics, etc.
        return


# Start listener as soon as module is imported (best-effort)
try:  # pragma: no cover - environment dependent
    if sync_mgr.connect():
        sync_mgr.start_listener(_handle_pubsub_message)
except Exception as e:  # pragma: no cover - defensive
    print(f"[WARN] Sync listener startup failed: {e}")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
def get_status() -> Dict[str, Any]:
    """Return sync subsystem status (for health checks & debug)."""
    status = sync_mgr.status()
    status.update(get_rejection_stats())
    return status


@router.post("/broadcast/block")
def broadcast_block(envelope: BlockEnvelope) -> Dict[str, Any]:
    """Broadcast a newly-finalized block to peers.

    This endpoint assumes the local node has *already* validated and
    committed the block to its own chain via the executor. We gate
    incoming blocks in `_handle_pubsub_message`, not here.
    """
    if not sync_mgr.client and not sync_mgr.connect():
        raise HTTPException(status_code=503, detail="Sync manager not connected")

    payload = {
        "type": "block",
        "block": envelope.block,
        "src": envelope.src or executor.node_id,  # type: ignore[attr-defined]
        "timestamp": int(time.time()),
    }
    ok = sync_mgr.publish(payload)
    if not ok:
        raise HTTPException(status_code=503, detail="Failed to publish block")

    return {"ok": True, "broadcast": payload}


@router.post("/broadcast/epoch")
def broadcast_epoch(envelope: Optional[EpochEnvelope] = None) -> Dict[str, Any]:
    """Publish current epoch to the network.

    This is mostly informational and can be ignored by peers.
    """
    if not sync_mgr.client and not sync_mgr.connect():
        raise HTTPException(status_code=503, detail="Sync manager not connected")

    epoch = (
        int(getattr(executor, "current_epoch", 0))
        if envelope is None
        else int(envelope.epoch)
    )
    payload = {
        "type": "epoch",
        "epoch": epoch,
        "height": (
            len(executor.ledger.get("chain", []))  # type: ignore[attr-defined]
        ),
        "block_id": envelope.block_id if envelope else None,
        "timestamp": int(time.time()),
    }
    ok = sync_mgr.publish(payload)
    if not ok:
        raise HTTPException(status_code=503, detail="Failed to publish epoch")

    return {"ok": True, "broadcast": payload}
