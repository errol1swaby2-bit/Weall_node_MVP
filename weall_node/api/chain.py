#!/usr/bin/env python3
"""
Chain API
------------------------------------
Exposes blockchain state, blocks, tokenomics metrics,
and (ship-mode) inclusion proofs.

Backed by the shared executor instance:
- ledger['chain'] as the source of truth
- ledger['tx_index'], ledger['tx_receipts'], ledger['tx_receipt_hashes']

Inclusion proof endpoint:
GET /chain/proof/{tx_id}
"""

import time
import logging
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.weall_runtime.ledger import INITIAL_EPOCH_REWARD, HALVING_INTERVAL

router = APIRouter(prefix="/chain", tags=["chain"])
logger = logging.getLogger("chain")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class BlockModel(BaseModel):
    """Public representation of a committed block."""
    height: int
    time: int
    proposer: str | None = None
    votes: list[str] = []
    prev_block_id: str | None = None
    block_id: str
    txs: list = []


def _get_core():
    """Normalize executor facade → core runtime."""
    return getattr(executor, "exec", executor)


def _get_chain_list() -> list[dict]:
    """Return the in-memory chain list from the executor ledger."""
    core = _get_core()
    ledger = getattr(core, "ledger", {}) or {}
    chain = ledger.get("chain") or []
    if not isinstance(chain, list):
        return []
    return [b for b in chain if isinstance(b, dict)]


def _ledger() -> Dict[str, Any]:
    core = _get_core()
    led = getattr(core, "ledger", {}) or {}
    return led if isinstance(led, dict) else {}


# ---------------------------
# Merkle proof utilities
# Must match the executor’s merkle_root leaf normalization:
#   leaf_node = SHA256(bytes.fromhex(leaf)) if leaf is hex else SHA256(leaf.encode)
#   parent = SHA256(left + right)
#   odd nodes duplicate
# ---------------------------

def _is_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return True
    except Exception:
        return False


def _leaf_digest_from_str(s: str) -> bytes:
    s = (s or "").strip().lower()
    if _is_hex(s) and len(s) % 2 == 0:
        raw = bytes.fromhex(s)
    else:
        raw = s.encode("utf-8")
    return hashlib.sha256(raw).digest()


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(a + b).digest()


def _merkle_root_and_proof(leaves: List[str], target: str) -> Tuple[str, Optional[dict]]:
    """
    Returns (root_hex, proof_dict or None)

    proof_dict:
      {
        "leaf": <target>,
        "leaf_hash": <hex>,
        "index": <int>,
        "path": [ {"side":"left"|"right","hash":<hex>}, ... ],
      }
    """
    leaves_norm = [str(x).strip().lower() for x in (leaves or []) if str(x).strip()]
    if not leaves_norm:
        root = hashlib.sha256(b"").hexdigest()
        return root, None

    target_norm = str(target).strip().lower()
    try:
        idx = leaves_norm.index(target_norm)
    except ValueError:
        # target not present
        root = _compute_merkle_root_hex(leaves_norm)
        return root, None

    level = [_leaf_digest_from_str(x) for x in leaves_norm]
    path: List[dict] = []
    index = idx

    while len(level) > 1:
        # If odd, duplicate last
        if len(level) % 2 == 1:
            level = level + [level[-1]]

        sibling_index = index ^ 1
        sibling_hash = level[sibling_index]

        if sibling_index < index:
            # sibling is left
            path.append({"side": "left", "hash": sibling_hash.hex()})
        else:
            # sibling is right
            path.append({"side": "right", "hash": sibling_hash.hex()})

        # build next level
        nxt: List[bytes] = []
        for i in range(0, len(level), 2):
            nxt.append(_hash_pair(level[i], level[i + 1]))
        level = nxt
        index //= 2

    root_hex = level[0].hex()
    proof = {
        "leaf": target_norm,
        "leaf_hash": _leaf_digest_from_str(target_norm).hex(),
        "index": int(idx),
        "path": path,
    }
    return root_hex, proof


def _compute_merkle_root_hex(leaves_norm: List[str]) -> str:
    if not leaves_norm:
        return hashlib.sha256(b"").hexdigest()
    level = [_leaf_digest_from_str(x) for x in leaves_norm]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level = level + [level[-1]]
        nxt: List[bytes] = []
        for i in range(0, len(level), 2):
            nxt.append(_hash_pair(level[i], level[i + 1]))
        level = nxt
    return level[0].hex()


# ---------------------------
# Existing endpoints
# ---------------------------

@router.get("/blocks")
def get_blocks() -> list[BlockModel]:
    """
    Return all committed blocks as BlockModel instances.

    Supports both legacy and newer executor block shapes.
    """
    try:
        blocks = _get_chain_list()
        logger.info("Fetched %s blocks", len(blocks))
        out: list[BlockModel] = []

        for b in blocks:
            header = b.get("header") or {}

            height = int(b.get("height", header.get("height", 0)))
            ts = int(b.get("time", b.get("ts", header.get("ts", 0))))

            proposer = b.get("proposer")
            votes = list(b.get("votes", []))

            prev_block_id = b.get("prev_block_id") or header.get("prev_id")
            block_id = b.get("block_id") or b.get("hash") or b.get("id") or ""

            txs = list(b.get("txs", []))

            out.append(
                BlockModel(
                    height=height,
                    time=ts,
                    proposer=proposer,
                    votes=votes,
                    prev_block_id=prev_block_id,
                    block_id=block_id,
                    txs=txs,
                )
            )

        return out
    except Exception as e:
        logger.exception("Failed to fetch blocks: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch blocks")


@router.get("/latest")
def get_latest() -> dict:
    """
    Return the raw latest block dict, if any.
    """
    try:
        blocks = _get_chain_list()
        blk = blocks[-1] if blocks else None
        if not blk:
            return {}
        logger.info("Fetched latest block height=%s", blk.get("height"))
        return blk
    except Exception as e:
        logger.exception("Failed to fetch latest block: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch latest block")


@router.get("/height")
def get_chain_height() -> dict:
    try:
        height = len(_get_chain_list())
        return {"ok": True, "height": height}
    except Exception as e:
        logger.exception("Height fetch failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get chain height")


@router.get("/tokenomics")
def tokenomics_status():
    """
    Return current tokenomics state, including epoch and pool membership.
    """
    try:
        core = _get_core()
        now = int(time.time())
        wecoin = getattr(core, "wecoin", None)
        if wecoin is not None:
            genesis_time = getattr(wecoin, "genesis_time", now)
            current_reward = wecoin.current_epoch_reward() if hasattr(wecoin, "current_epoch_reward") else INITIAL_EPOCH_REWARD
        else:
            genesis = getattr(core, "genesis", {}) or {}
            genesis_time = int(genesis.get("genesis_time") or now)
            current_reward = INITIAL_EPOCH_REWARD

        elapsed = max(0, now - genesis_time)
        halvings = elapsed // HALVING_INTERVAL
        next_halving_eta = HALVING_INTERVAL - (elapsed % HALVING_INTERVAL)

        pools: dict[str, dict[str, object]] = {}
        raw_pools = getattr(wecoin, "pools", {}) if wecoin is not None else {}
        if isinstance(raw_pools, dict):
            for name, meta in raw_pools.items():
                if isinstance(meta, dict):
                    members = list(meta.get("members", []))
                else:
                    members = list(meta or [])
                pools[name] = {"count": len(members), "members": members}

        return {
            "epoch": int(getattr(core, "current_epoch", 0)),
            "bootstrap_mode": bool(getattr(core, "bootstrap_mode", False)),
            "min_validators": int(getattr(core, "min_validators", 0)),
            "initial_epoch_reward": INITIAL_EPOCH_REWARD,
            "total_epoch_reward": current_reward,
            "halvings_so_far": int(halvings),
            "next_halving_in_seconds": int(next_halving_eta),
            "pools": pools,
        }
    except Exception as e:
        logger.exception("Tokenomics query failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch tokenomics status")


# ---------------------------
# NEW: Inclusion proof endpoint
# ---------------------------

@router.get("/proof/{tx_id}")
def get_inclusion_proof(tx_id: str) -> Dict[str, Any]:
    """
    Return inclusion proof for a tx_id:
    - block location (height, block_id, proposal_id)
    - tx merkle proof to header.txs_root
    - receipt hash merkle proof to header.receipts_root
    - stored receipt (if any)
    """
    tx_id_norm = (tx_id or "").strip().lower()
    if not tx_id_norm:
        raise HTTPException(status_code=400, detail="tx_id_required")

    led = _ledger()
    tx_index = led.get("tx_index", {})
    if not isinstance(tx_index, dict):
        tx_index = {}

    meta = tx_index.get(tx_id_norm)
    if not isinstance(meta, dict):
        # Some callers may provide uppercase, try exact key search
        # (but we keep response deterministic and safe)
        for k, v in tx_index.items():
            if str(k).strip().lower() == tx_id_norm and isinstance(v, dict):
                meta = v
                tx_id_norm = str(k).strip().lower()
                break

    if not isinstance(meta, dict) or not meta:
        raise HTTPException(status_code=404, detail="tx_not_indexed")

    try:
        height = int(meta.get("height", 0) or 0)
    except Exception:
        height = 0

    chain = _get_chain_list()
    if height < 0 or height >= len(chain):
        raise HTTPException(status_code=404, detail="block_missing_for_tx")

    block = chain[height]
    header = block.get("header") if isinstance(block.get("header"), dict) else {}
    txs_root_expected = str(header.get("txs_root") or "")
    receipts_root_expected = str(header.get("receipts_root") or "")

    # Collect tx_ids in block order
    txs = block.get("txs", [])
    if not isinstance(txs, list):
        txs = []

    tx_ids: List[str] = []
    for item in txs:
        if isinstance(item, dict):
            tid = str(item.get("tx_id") or "").strip().lower()
            if tid:
                tx_ids.append(tid)

    # Collect receipt hashes in same order as tx_ids (where available)
    tx_receipt_hashes = led.get("tx_receipt_hashes", {})
    if not isinstance(tx_receipt_hashes, dict):
        tx_receipt_hashes = {}
    receipt_hashes: List[str] = []
    for tid in tx_ids:
        rh = tx_receipt_hashes.get(tid)
        if isinstance(rh, str) and rh.strip():
            receipt_hashes.append(rh.strip().lower())
        else:
            # If missing, we still keep positional alignment by adding an empty placeholder.
            # But placeholders would break proofs, so we only include present hashes.
            # That means receipts_root proof is available only if the receipt hash exists.
            pass

    # Build tx proof
    txs_root, tx_proof = _merkle_root_and_proof(tx_ids, tx_id_norm)

    # Build receipt proof (only if we can find receipt hash)
    receipt = None
    receipt_hash_hex = None
    receipt_proof = None
    receipts_root = None

    tx_receipts = led.get("tx_receipts", {})
    if isinstance(tx_receipts, dict):
        r = tx_receipts.get(tx_id_norm)
        if isinstance(r, dict):
            receipt = r

    if isinstance(tx_receipt_hashes, dict):
        rh = tx_receipt_hashes.get(tx_id_norm)
        if isinstance(rh, str) and rh.strip():
            receipt_hash_hex = rh.strip().lower()
            receipts_root, receipt_proof = _merkle_root_and_proof(receipt_hashes, receipt_hash_hex)
        else:
            receipts_root = _compute_merkle_root_hex(receipt_hashes)

    # Validate computed roots against header (if header has them)
    roots_ok = True
    root_checks: Dict[str, Any] = {}

    if txs_root_expected:
        root_checks["txs_root_expected"] = txs_root_expected
        root_checks["txs_root_computed"] = txs_root
        if txs_root_expected.lower() != txs_root.lower():
            roots_ok = False

    if receipts_root_expected:
        root_checks["receipts_root_expected"] = receipts_root_expected
        root_checks["receipts_root_computed"] = receipts_root or ""
        if (receipts_root or "").lower() != receipts_root_expected.lower():
            # If we couldn't build receipts_root (missing receipt hashes), mark mismatch
            roots_ok = False

    block_id = str(block.get("block_id") or block.get("id") or "")
    proposal_id = str(block.get("proposal_id") or "")
    prev_block_id = str(block.get("prev_block_id") or header.get("prev_id") or "")
    proposer = block.get("proposer")

    out = {
        "ok": True,
        "tx_id": tx_id_norm,
        "location": {
            "height": height,
            "block_id": block_id,
            "proposal_id": proposal_id,
            "prev_block_id": prev_block_id,
            "proposer": proposer,
        },
        "header": {
            "txs_root": txs_root_expected or txs_root,
            "receipts_root": receipts_root_expected or (receipts_root or ""),
        },
        "tx_proof": tx_proof,
        "receipt": receipt,
        "receipt_hash": receipt_hash_hex,
        "receipt_proof": receipt_proof,
        "roots_ok": roots_ok,
        "root_checks": root_checks,
    }

    # If tx_proof is missing, report clearly
    if tx_proof is None:
        out["ok"] = False
        out["error"] = "tx_not_in_block_list"

    # If receipt hash exists but proof missing, report clearly (still return tx proof)
    if receipt_hash_hex and receipt_proof is None:
        out["receipt_error"] = "receipt_hash_not_in_receipts_list"

    return out
