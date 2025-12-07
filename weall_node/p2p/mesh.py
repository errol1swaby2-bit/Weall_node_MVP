#!/usr/bin/env python3
"""
WeAll P2P Mesh
-------------------------------
Lightweight peer overlay helpers for WeAll:

- Node identity: Ed25519 persisted as node_id.json
- Peer registry with TTL + disk cache (peers.json)
- Module-level helpers to init and access the registry + identity

Higher-level APIs (sync, messaging, etc.) are built on top of this.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

log = logging.getLogger(__name__)

NODE_ID_FILE = "node_id.json"
PEERS_FILE = "peers.json"
DEFAULT_TTL_SEC = 24 * 3600  # 1 day


# ---------------------------------------------------------------------------
# Node identity
# ---------------------------------------------------------------------------


class NodeIdentity:
    """
    Small wrapper around an Ed25519 keypair stored on disk.

    JSON format (node_id.json):

        {
          "node_id": "node:abcd1234ef56",
          "ed25519_priv": "<64 hex chars>",
          "pub_hex": "<64 hex chars>"
        }
    """

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root
        self.path = os.path.join(repo_root, NODE_ID_FILE)
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

    def _load_or_create(self) -> None:
        """
        Load existing identity from node_id.json if possible, otherwise create
        a new keypair and persist it.
        """
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                hex_priv = data.get("ed25519_priv")
                if hex_priv:
                    priv_bytes = bytes.fromhex(hex_priv)
                    self._priv = ed25519.Ed25519PrivateKey.from_private_bytes(
                        priv_bytes
                    )
                    pub_hex = self._derive_pub_hex()
                    self._pub_hex = data.get("pub_hex") or pub_hex
                    # Prefer deterministic node_id from public key
                    self._node_id = data.get("node_id") or f"node:{pub_hex[:12]}"
                    # Normalize persisted format if anything changed
                    if (
                        data.get("pub_hex") != self._pub_hex
                        or data.get("node_id") != self._node_id
                    ):
                        self._save()
                    return
        except Exception as exc:  # defensive only
            log.warning("Failed to load node identity; regenerating: %s", exc)

        # If we reach here, generate a new identity
        self._priv = ed25519.Ed25519PrivateKey.generate()
        self._pub_hex = self._derive_pub_hex()
        self._node_id = f"node:{self._pub_hex[:12]}"
        self._save()

    def _derive_pub_hex(self) -> str:
        assert self._priv is not None
        pub = self._priv.public_key()
        raw = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    def _save(self) -> None:
        assert self._priv is not None
        assert self._pub_hex is not None
        assert self._node_id is not None

        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
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

    def sign(self, payload: bytes) -> str:
        """
        Sign an arbitrary payload and return the signature as hex.
        """
        assert self._priv is not None
        sig = self._priv.sign(payload)
        return sig.hex()

    def build_announce(
        self, addr: str = "", meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Convenience helper for building a signed /p2p/announce payload.
        """
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
# Peer registry
# ---------------------------------------------------------------------------


@dataclass
class PeerRecord:
    node_id: str
    addr: str = ""
    last_seen: float = field(default_factory=lambda: time.time())
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "addr": self.addr,
            "last_seen": self.last_seen,
            "meta": self.meta,
        }


class PeerRegistry:
    """
    In-memory + on-disk registry of known peers.

    - Disk format is a JSON object mapping node_id -> PeerRecord-like dict
    - TTL-based pruning keeps the list from growing without bound
    """

    def __init__(self, repo_root: str, ttl_sec: int = DEFAULT_TTL_SEC) -> None:
        self.repo_root = repo_root
        self.path = os.path.join(repo_root, PEERS_FILE)
        self.ttl_sec = ttl_sec
        self._lock = threading.RLock()
        self._peers: Dict[str, PeerRecord] = {}
        self._load()
        self._prune()

    # ----- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            for node_id, rec in data.items():
                try:
                    last_seen = float(rec.get("last_seen", now))
                    if now - last_seen > self.ttl_sec:
                        continue
                    self._peers[node_id] = PeerRecord(
                        node_id=node_id,
                        addr=rec.get("addr", "") or "",
                        last_seen=last_seen,
                        meta=rec.get("meta") or {},
                    )
                except Exception:
                    continue
        except Exception as exc:  # defensive
            log.warning("Failed to load peer registry: %s", exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            payload = {nid: rec.to_dict() for nid, rec in self._peers.items()}
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except Exception as exc:  # defensive
            log.warning("Failed to save peer registry: %s", exc)

    # ----- core operations ---------------------------------------------------

    def _prune_locked(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        cutoff = now - self.ttl_sec
        stale = [nid for nid, rec in self._peers.items() if rec.last_seen < cutoff]
        for nid in stale:
            self._peers.pop(nid, None)

    def _prune(self) -> None:
        with self._lock:
            self._prune_locked()
            self._save()

    def upsert_peer(
        self, node_id: str, addr: str = "", meta: Optional[Dict[str, Any]] = None
    ) -> PeerRecord:
        """
        Insert or update a peer and persist the registry.
        """
        if not node_id:
            raise ValueError("node_id is required")
        now = time.time()
        meta = meta or {}
        with self._lock:
            rec = self._peers.get(node_id)
            if rec:
                if addr:
                    rec.addr = addr
                rec.meta.update(meta)
                rec.last_seen = now
            else:
                rec = PeerRecord(node_id=node_id, addr=addr, last_seen=now, meta=meta)
                self._peers[node_id] = rec
            self._prune_locked(now)
            self._save()
            return rec

    def list_peer_ids(self) -> List[str]:
        with self._lock:
            return sorted(self._peers.keys())

    def snapshot(self) -> List[Dict[str, Any]]:
        """
        Return a list of peer dicts (for APIs / debugging).
        """
        with self._lock:
            return [
                rec.to_dict()
                for rec in sorted(
                    self._peers.values(),
                    key=lambda r: r.last_seen,
                    reverse=True,
                )
            ]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_registry: Optional[PeerRegistry] = None
_identity: Optional[NodeIdentity] = None


def init_p2p(repo_root: str) -> Tuple[PeerRegistry, NodeIdentity]:
    """
    Initialize the global peer registry + node identity for this process.

    Safe to call multiple times; subsequent calls return the existing singletons.
    """
    global _registry, _identity
    if _registry is not None and _identity is not None:
        return _registry, _identity
    _registry = PeerRegistry(repo_root)
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
