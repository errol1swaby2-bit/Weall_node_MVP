#!/usr/bin/env python3
"""weall_node/p2p/mesh.py
--------------------------------
Lightweight peer overlay helpers for WeAll.

This module is intentionally *small* and *stdlib-friendly* so it runs well on
Android/Termux phones.

What it provides
----------------
* **Node identity** (Ed25519) persisted to ``WEALL_DATA_DIR/node_id.json``
* **Peer registry** persisted to ``WEALL_DATA_DIR/peers.json``
  - TTL pruning
  - basic reliability scoring (success/failure)
  - a small "local_meta" namespace used by background gossip/PEX

Higher-level APIs (sync, messaging, etc.) build on top of this.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

log = logging.getLogger(__name__)

NODE_ID_FILE = "node_id.json"
PEERS_FILE = "peers.json"
DEFAULT_TTL_SEC = 24 * 3600  # 1 day
DEFAULT_MAX_PEERS = 500


# ---------------------------------------------------------------------------
# Node identity
# ---------------------------------------------------------------------------


class NodeIdentity:
    """
    Node identity helper with Ed25519 signing.

    JSON format (node_id.json):

        {
          "node_id": "<short id>",
          "ed25519_priv": "<64 hex chars>",
          "pub_hex": "<64 hex chars>"
        }

    IMPORTANT:
      - This file MUST live in WEALL_DATA_DIR (runtime-local).
      - Do NOT commit or ship this file in repo artifacts.
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

        # Persist identity in the runtime data dir, not repo root.
        data_dir = os.getenv("WEALL_DATA_DIR", os.path.join(repo_root, "data"))
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, NODE_ID_FILE)

        self._priv: Optional[ed25519.Ed25519PrivateKey] = None
        self._pub_hex: Optional[str] = None
        self._node_id: Optional[str] = None
        self._load_or_create()

    # ----- public properties -------------------------------------------------

    @property
    def node_id(self) -> str:
        assert self._node_id is not None
        return self._node_id

    @property
    def pub_hex(self) -> str:
        assert self._pub_hex is not None
        return self._pub_hex

    # ----- persistence -------------------------------------------------------

    def _derive_pub_hex(self) -> str:
        assert self._priv is not None
        pub = self._priv.public_key()
        raw = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    def _load_or_create(self) -> None:
        """
        Load existing identity from WEALL_DATA_DIR/node_id.json if possible,
        otherwise create a new keypair and persist it.
        """
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                hex_priv = data.get("ed25519_priv")
                if hex_priv:
                    priv_bytes = bytes.fromhex(hex_priv)
                    self._priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
                    self._pub_hex = self._derive_pub_hex()
                    self._node_id = str(data.get("node_id") or "")[:16] or self._pub_hex[:16]
                    return
        except Exception:
            log.warning("Failed loading node identity; generating new identity", exc_info=True)

        # Create new
        self._priv = ed25519.Ed25519PrivateKey.generate()
        self._pub_hex = self._derive_pub_hex()
        self._node_id = self._pub_hex[:16]

        # Persist atomically
        priv_bytes = self._priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        data = {
            "node_id": self._node_id,
            "ed25519_priv": priv_bytes.hex(),
            "pub_hex": self._pub_hex,
        }
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    # ----- signing helpers ---------------------------------------------------

    def sign(self, message: bytes) -> str:
        assert self._priv is not None
        return self._priv.sign(message).hex()

    def verify(self, message: bytes, signature_hex: str, pub_hex: Optional[str] = None) -> bool:
        try:
            pub_hex = pub_hex or self.pub_hex
            pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
            pub.verify(bytes.fromhex(signature_hex), message)
            return True
        except Exception:
            return False

    # ----- handshake helper --------------------------------------------------

    def signed_hello(self, addr: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ts = int(time.time())
        nonce = os.urandom(8).hex()
        meta = meta or {}
        message = f"{self.node_id}|{addr}|{ts}|{nonce}".encode("utf-8")
        signature = self.sign(message)
        return {
            "node_id": self.node_id,
            "addr": addr,
            "ts": ts,
            "nonce": nonce,
            "meta": meta,
            "pub_hex": self.pub_hex,
            "signature": signature,
        }


# ---------------------------------------------------------------------------
# Peer Registry
# ---------------------------------------------------------------------------


@dataclass
class PeerRecord:
    node_id: str
    addr: str
    last_seen: float
    meta: Dict[str, Any]

    # Reliability stats (used for scoring / peer selection)
    ok_count: int = 0
    fail_count: int = 0
    last_ok: float = 0.0
    last_fail: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "addr": self.addr,
            "last_seen": self.last_seen,
            "meta": dict(self.meta or {}),
            "ok_count": int(self.ok_count),
            "fail_count": int(self.fail_count),
            "last_ok": float(self.last_ok),
            "last_fail": float(self.last_fail),
        }


class PeerRegistry:
    def __init__(self, path: str, ttl_sec: int = DEFAULT_TTL_SEC) -> None:
        self.path = path
        self.ttl_sec = int(ttl_sec)
        self._lock = threading.Lock()
        self._peers: Dict[str, PeerRecord] = {}
        self._local_meta: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return
            # local_meta is optional; used for gossip bookkeeping.
            local_meta = raw.get("local_meta")
            if isinstance(local_meta, dict):
                self._local_meta = local_meta
            peers = raw.get("peers")
            if not isinstance(peers, dict):
                return
            for node_id, rec in peers.items():
                if not isinstance(rec, dict):
                    continue
                self._peers[str(node_id)] = PeerRecord(
                    node_id=str(node_id),
                    addr=str(rec.get("addr") or ""),
                    last_seen=float(rec.get("last_seen") or 0.0),
                    meta=rec.get("meta") if isinstance(rec.get("meta"), dict) else {},
                    ok_count=int(rec.get("ok_count") or 0),
                    fail_count=int(rec.get("fail_count") or 0),
                    last_ok=float(rec.get("last_ok") or 0.0),
                    last_fail=float(rec.get("last_fail") or 0.0),
                )
        except Exception:
            log.warning("Failed to load peers cache", exc_info=True)

    def _save(self) -> None:
        try:
            data = {
                "local_meta": self._local_meta,
                "peers": {
                    node_id: {
                        "addr": rec.addr,
                        "last_seen": rec.last_seen,
                        "meta": rec.meta,
                        "ok_count": rec.ok_count,
                        "fail_count": rec.fail_count,
                        "last_ok": rec.last_ok,
                        "last_fail": rec.last_fail,
                    }
                    for node_id, rec in self._peers.items()
                }
            }
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except Exception:
            log.warning("Failed to save peers cache", exc_info=True)

    def _prune_locked(self) -> None:
        now = time.time()
        dead = [nid for nid, rec in self._peers.items() if now - rec.last_seen > self.ttl_sec]
        for nid in dead:
            self._peers.pop(nid, None)

    def list_peers(self) -> Dict[str, PeerRecord]:
        with self._lock:
            self._prune_locked()
            return dict(self._peers)

    # ------------------------------------------------------------------
    # Compatibility helpers (used by /api/p2p_overlay)
    # ------------------------------------------------------------------

    def snapshot(self) -> List[Dict[str, Any]]:
        """Return a JSON-serializable snapshot of peers."""
        with self._lock:
            self._prune_locked()
            return [self._to_dict(rec) for rec in self._peers.values()]

    def snapshot_scored(self) -> List[Dict[str, Any]]:
        """Snapshot with computed score (higher = better)."""
        with self._lock:
            self._prune_locked()
            out = []
            for rec in self._peers.values():
                d = self._to_dict(rec)
                d["score"] = self._score(rec)
                out.append(d)
            out.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
            return out

    def prune_to_max(self, max_peers: int = DEFAULT_MAX_PEERS) -> None:
        """Hard-cap the peer set (keeps best scored + most recent)."""
        max_peers = int(max_peers)
        if max_peers <= 0:
            return
        with self._lock:
            self._prune_locked()
            if len(self._peers) <= max_peers:
                return
            # Keep high-score / recent peers.
            ranked = sorted(
                self._peers.values(),
                key=lambda r: (self._score(r), r.last_seen),
                reverse=True,
            )
            keep = {r.node_id for r in ranked[:max_peers]}
            self._peers = {nid: rec for nid, rec in self._peers.items() if nid in keep}
            self._save()

    def touch_local_meta(self, updates: Dict[str, Any]) -> None:
        """Merge updates into local_meta and persist."""
        if not isinstance(updates, dict):
            return
        with self._lock:
            self._local_meta.update(updates)
            self._save()

    def get_local_meta(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._local_meta)

    # ------------------------------------------------------------------
    # Reliability tracking
    # ------------------------------------------------------------------

    def mark_ok(self, node_id: str) -> None:
        if not node_id:
            return
        with self._lock:
            rec = self._peers.get(node_id)
            if rec is None:
                rec = PeerRecord(node_id=node_id, addr="", last_seen=time.time(), meta={})
                self._peers[node_id] = rec
            rec.ok_count += 1
            rec.last_ok = time.time()
            rec.last_seen = time.time()
            self._prune_locked()
            self._save()

    def mark_fail(self, node_id: str) -> None:
        if not node_id:
            return
        with self._lock:
            rec = self._peers.get(node_id)
            if rec is None:
                rec = PeerRecord(node_id=node_id, addr="", last_seen=time.time(), meta={})
                self._peers[node_id] = rec
            rec.fail_count += 1
            rec.last_fail = time.time()
            self._prune_locked()
            self._save()

    def touch_peer(self, node_id: str) -> None:
        if not node_id:
            return
        with self._lock:
            rec = self._peers.get(node_id)
            if rec:
                rec.last_seen = time.time()
            self._prune_locked()
            self._save()

    def upsert_peer(self, node_id: str, addr: str = "", meta: Optional[Dict[str, Any]] = None) -> PeerRecord:
        if not node_id:
            raise ValueError("node_id is required")
        now = time.time()
        meta = meta or {}
        with self._lock:
            rec = self._peers.get(node_id)
            if rec is None:
                rec = PeerRecord(node_id=node_id, addr=addr, last_seen=now, meta=meta)
                self._peers[node_id] = rec
            else:
                rec.addr = addr or rec.addr
                rec.last_seen = now
                rec.meta.update(meta)
            self._prune_locked()
            self._save()
            return rec

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dict(rec: PeerRecord) -> Dict[str, Any]:
        return {
            "node_id": rec.node_id,
            "addr": rec.addr,
            "last_seen": rec.last_seen,
            "meta": rec.meta,
            "ok_count": rec.ok_count,
            "fail_count": rec.fail_count,
            "last_ok": rec.last_ok,
            "last_fail": rec.last_fail,
        }

    @staticmethod
    def _score(rec: PeerRecord) -> float:
        """
        A simple, explainable scoring function.

        Signals:
          - more successes (ok_count) is better
          - more failures (fail_count) is worse
          - recent success is better than stale success
          - recent failure penalizes short-term
        """
        now = time.time()
        ok = float(rec.ok_count)
        fail = float(rec.fail_count)

        # Recency boosts/penalties (0..1 scale)
        ok_age = max(0.0, now - float(rec.last_ok or 0.0))
        fail_age = max(0.0, now - float(rec.last_fail or 0.0))

        ok_recency = 1.0 / (1.0 + ok_age / 300.0)  # ~5 min half-life-ish
        fail_recency = 1.0 / (1.0 + fail_age / 300.0)

        # Base: successes - failures
        base = ok - 1.25 * fail

        # Add recency: recent ok helps, recent fail hurts
        score = base + (2.0 * ok_recency) - (2.5 * fail_recency)

        # Clamp lightly (avoid huge numbers)
        return float(max(-50.0, min(50.0, score)))


# ---------------------------------------------------------------------------
# Module-level initialization
# ---------------------------------------------------------------------------

_registry: Optional[PeerRegistry] = None
_identity: Optional[NodeIdentity] = None


def init_p2p(repo_root: str) -> Tuple[PeerRegistry, NodeIdentity]:
    global _registry, _identity

    # Cache peers in WEALL_DATA_DIR as well
    data_dir = os.getenv("WEALL_DATA_DIR", os.path.join(repo_root, "data"))
    os.makedirs(data_dir, exist_ok=True)
    peers_path = os.path.join(data_dir, PEERS_FILE)

    _registry = PeerRegistry(peers_path)
    _identity = NodeIdentity(repo_root)
    log.info("[p2p] node_id=%s", _identity.node_id)
    return _registry, _identity


def get_registry() -> PeerRegistry:
    if _registry is None:
        raise RuntimeError("P2P registry not initialized; call init_p2p() first")
    return _registry


def get_identity() -> NodeIdentity:
    if _identity is None:
        raise RuntimeError("P2P identity not initialized; call init_p2p() first")
    return _identity
