from __future__ import annotations

"""
weall_node.weall_runtime.txpool

Canonical protobuf TX lane utilities used by:
- weall_node/api/tx.py
- weall_node/api/tx_sync.py
- weall_node/api/proto.py (compat)

Rules:
- Generated protobuf modules are imported from weall.v1
- No runtime proto folders, no sys.path hacks
"""

import base64
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from weall.v1 import tx_pb2

from .proto_codec import ProtoDomain
from .proto_verify import verify_tx_envelope, TxVerificationError


# -----------------------------------------------------------------------------
# Domain (network binding)
# -----------------------------------------------------------------------------
DOMAIN = ProtoDomain(chain_id="weall-local", schema_version=1)


# -----------------------------------------------------------------------------
# Seen-set (pubsub replay dampening)
# -----------------------------------------------------------------------------
class SeenSet:
    def __init__(self, ttl_sec: int = 600):
        self.ttl_sec = ttl_sec
        self._m: Dict[str, float] = {}

    def _gc(self) -> None:
        now = time.time()
        dead = [k for k, ts in self._m.items() if now - ts > self.ttl_sec]
        for k in dead:
            self._m.pop(k, None)

    def has(self, tx_id_hex: str) -> bool:
        self._gc()
        ts = self._m.get(tx_id_hex)
        if ts is None:
            return False
        return (time.time() - ts) <= self.ttl_sec

    def mark(self, tx_id_hex: str) -> None:
        self._gc()
        self._m[tx_id_hex] = time.time()


SEEN = SeenSet(ttl_sec=600)


# -----------------------------------------------------------------------------
# Receipts (lightweight)
# -----------------------------------------------------------------------------
@dataclass
class TxReceipt:
    tx_id_hex: str
    ok: bool
    status: str
    source: str
    seen_ms: int


_RECEIPTS: Dict[str, TxReceipt] = {}


def receipts_put(tx_id_hex: str, ok: bool, status: str, source: str) -> None:
    _RECEIPTS[tx_id_hex] = TxReceipt(
        tx_id_hex=tx_id_hex,
        ok=ok,
        status=status,
        source=source,
        seen_ms=int(time.time() * 1000),
    )


def receipts_get(tx_id_hex: str) -> Optional[dict]:
    r = _RECEIPTS.get(tx_id_hex)
    if not r:
        return None
    return {
        "tx_id": r.tx_id_hex,
        "ok": r.ok,
        "status": r.status,
        "source": r.source,
        "seen_ms": r.seen_ms,
    }


# -----------------------------------------------------------------------------
# Encoding helpers (used by tx_sync)
# -----------------------------------------------------------------------------
def encode_b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def decode_b64(raw_b64: str) -> bytes:
    return base64.b64decode(raw_b64.encode("ascii"))


# -----------------------------------------------------------------------------
# Pool item shape (must match existing API expectations)
# -----------------------------------------------------------------------------
@dataclass
class PoolItem:
    tx_id: bytes
    tx: tx_pb2.TxEnvelope
    raw: bytes
    received_ms: int
    source: str


@dataclass
class Mempool:
    domain: ProtoDomain
    items: Dict[bytes, PoolItem] = field(default_factory=dict)

    def size(self) -> int:
        return len(self.items)

    def list_tx_ids_hex(self, limit: int = 50) -> List[str]:
        ordered = sorted(self.items.items(), key=lambda kv: kv[1].received_ms)
        out: List[str] = []
        for txid, _item in ordered[: max(0, int(limit))]:
            out.append(txid.hex())
        return out

    def get(self, txid: bytes) -> Optional[PoolItem]:
        return self.items.get(txid)

    def add(self, env: tx_pb2.TxEnvelope, raw: bytes, source: str) -> Tuple[Optional[PoolItem], bool, str]:
        txid = bytes(env.tx_id)
        if not txid:
            return None, False, "tx_id missing"

        if txid in self.items:
            return self.items[txid], False, "duplicate"

        try:
            verify_tx_envelope(self.domain, env)
        except TxVerificationError as e:
            return None, False, f"verify_failed: {e}"

        item = PoolItem(tx_id=txid, tx=env, raw=raw, received_ms=int(time.time() * 1000), source=source)
        self.items[txid] = item
        return item, True, "ok"

    def pop_batch(self, max_n: int) -> List[PoolItem]:
        if max_n <= 0:
            return []
        ordered = sorted(self.items.items(), key=lambda kv: kv[1].received_ms)
        picked = ordered[:max_n]
        for txid, _item in picked:
            self.items.pop(txid, None)
        return [item for _txid, item in picked]


MEMPOOL = Mempool(domain=DOMAIN)


# -----------------------------------------------------------------------------
# Ingest raw tx bytes (used by API + pubsub sync)
# -----------------------------------------------------------------------------
def ingest_raw_tx(raw: bytes, source: str = "local") -> Tuple[PoolItem, bool]:
    """
    Decode + verify + mempool-add.

    Returns:
      (PoolItem, is_new)

    Raises:
      ValueError on decode/verify failures (API maps to 400)
    """
    try:
        env = tx_pb2.TxEnvelope.FromString(raw)
    except Exception as e:
        receipts_put(tx_id_hex="", ok=False, status="decode_failed", source=source)
        raise ValueError(f"decode_failed: {e}") from e

    tx_id_hex = bytes(env.tx_id).hex() if env.tx_id else ""

    item, is_new, status = MEMPOOL.add(env, raw, source=source)
    ok = status in ("ok", "duplicate")
    receipts_put(tx_id_hex=tx_id_hex, ok=ok, status=status, source=source)

    if item is None:
        raise ValueError(status)

    return item, is_new
