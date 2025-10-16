#!/usr/bin/env python3
"""
WeAll P2P Mesh — peer discovery, signed handshake, encrypted WS signaling.

- Node identity: Ed25519 persisted (node_id.json)
- Signed announcements: /p2p/announce (ts+nonce)
- Peer registry with TTL + disk cache (peers.json)
- WS signaling rooms with optional AES-GCM encryption via shared 'secret'
- Room tokens: /p2p/handshake
- Helpers for periodic gossip (driven from API on startup)
"""

from __future__ import annotations
import os, json, time, secrets, logging, pathlib, threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import ed25519

log = logging.getLogger("weall.p2p")

NODE_ID_FILE = "node_id.json"
PEERS_FILE    = "peers.json"
DEFAULT_TTL   = 60 * 15  # 15m
NONCE_TTL     = 60 * 30  # 30m (replay window)

@dataclass
class Peer:
    node_id: str
    public_key: str      # hex
    url: str             # base URL "https://node.example"
    addrs: List[str]
    capabilities: List[str] = field(default_factory=list)
    last_seen: float = field(default_factory=lambda: time.time())
    ttl: int = DEFAULT_TTL
    def as_dict(self):
        return {
            "node_id": self.node_id,
            "public_key": self.public_key,
            "url": self.url,
            "addrs": self.addrs,
            "capabilities": self.capabilities,
            "last_seen": self.last_seen,
            "ttl": self.ttl,
            "expires": self.last_seen + self.ttl,
        }

class NodeIdentity:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.path = os.path.join(repo_root, NODE_ID_FILE)
        self._priv: Optional[ed25519.Ed25519PrivateKey] = None
        self._pub_hex: Optional[str] = None
        self._node_id: Optional[str] = None
        self._load_or_create()
    @property
    def node_id(self): return self._node_id
    @property
    def pub_hex(self): return self._pub_hex
    def sign(self, msg: bytes) -> str:
        return self._priv.sign(msg).hex()
    def _load_or_create(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r") as f: data = json.load(f)
                priv_bytes = bytes.fromhex(data["ed25519_priv"])
                self._priv = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
                pub = self._priv.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
                self._pub_hex = pub.hex()
                self._node_id = data.get("node_id") or self._pub_hex[:16]
                return
        except Exception as e:
            log.warning(f"[node_id] failed to load, regenerating: {e}")
        self._priv = ed25519.Ed25519PrivateKey.generate()
        pub = self._priv.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
        self._pub_hex = pub.hex()
        self._node_id = self._pub_hex[:16]
        try:
            with open(self.path, "w") as f:
                json.dump({
                    "node_id": self._node_id,
                    "ed25519_priv": self._priv.private_bytes(
                        ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption()
                    ).hex(),
                }, f, indent=2)
        except Exception as e:
            log.error(f"[node_id] save error: {e}")

@dataclass
class RoomClient:
    uid: str
    send: Callable[[dict], None]

class PeerRegistry:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.path = os.path.join(repo_root, PEERS_FILE)
        self._lock = threading.RLock()
        self._peers: Dict[str, Peer] = {}
        self._rooms: Dict[str, Dict[str, RoomClient]] = {}   # token -> uid -> client
        self._room_secrets: Dict[str, bytes] = {}            # token -> 32B AES-GCM key
        self._announce_nonces: Dict[str, float] = {}         # nonce->expiry
        self._load()
    # ------------ persistence ------------
    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r") as f: raw = json.load(f)
                now = time.time()
                for node_id, p in raw.items():
                    if p.get("expires", 0) > now:
                        self._peers[node_id] = Peer(
                            node_id=p["node_id"], public_key=p["public_key"], url=p["url"],
                            addrs=p.get("addrs", []), capabilities=p.get("capabilities", []),
                            last_seen=p.get("last_seen", now), ttl=int(p.get("ttl", DEFAULT_TTL))
                        )
        except Exception as e:
            log.warning(f"[peers] load error: {e}")
    def _save(self):
        try:
            with open(self.path, "w") as f:
                json.dump({k:v.as_dict() for k,v in self._peers.items()}, f, indent=2)
        except Exception as e:
            log.warning(f"[peers] save error: {e}")
    # ------------ peers ------------
    def upsert_peer(self, p: Peer):
        with self._lock:
            self._peers[p.node_id] = p
            self._save()
    def list_peers(self) -> List[dict]:
        with self._lock:
            now = time.time()
            for k in [k for k,v in self._peers.items() if (v.last_seen + v.ttl) < now]:
                self._peers.pop(k, None)
            return [p.as_dict() for p in self._peers.values()]
    # ------------ nonces (replay) ------------
    def nonce_seen(self, nonce: str) -> bool:
        with self._lock:
            now = time.time()
            # prune
            for k in [k for k,exp in self._announce_nonces.items() if exp < now]:
                self._announce_nonces.pop(k, None)
            if nonce in self._announce_nonces: return True
            self._announce_nonces[nonce] = now + NONCE_TTL
            return False
    # ------------ signaling rooms ------------
    def new_token(self) -> str: return secrets.token_urlsafe(16)
    def new_secret(self) -> bytes: return secrets.token_bytes(32)  # AES-GCM key
    def set_room_secret(self, token: str, key: bytes): self._room_secrets[token] = key
    def get_room_secret(self, token: str) -> Optional[bytes]: return self._room_secrets.get(token)
    def del_room_secret(self, token: str): self._room_secrets.pop(token, None)
    def join_room(self, token: str, uid: str, send_callable):
        with self._lock:
            room = self._rooms.setdefault(token, {})
            room[uid] = RoomClient(uid=uid, send=send_callable)
            return list(room.keys())
    def leave_room(self, token: str, uid: str):
        with self._lock:
            room = self._rooms.get(token)
            if not room: return
            room.pop(uid, None)
            if not room:
                self._rooms.pop(token, None)
                self.del_room_secret(token)
    def relay(self, token: str, from_uid: str, payload: dict):
        with self._lock:
            room = self._rooms.get(token, {})
            for uid, c in room.items():
                if uid == from_uid: continue
                try: c.send(payload)
                except Exception: pass

# --------- helpers ----------
def verify_signature(pub_hex: str, message: bytes, sig_hex: str) -> bool:
    try:
        pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(bytes.fromhex(sig_hex), message)
        return True
    except Exception:
        return False

# --------- module singletons ----------
_registry: Optional[PeerRegistry] = None
_identity: Optional[NodeIdentity] = None
def init_mesh(repo_root: str):
    global _registry, _identity
    if _registry and _identity: return _registry, _identity
    _registry = PeerRegistry(repo_root)
    _identity = NodeIdentity(repo_root)
    log.info(f"[p2p] node_id={_identity.node_id}")
    return _registry, _identity
def get_registry() -> PeerRegistry: return _registry
def get_identity() -> NodeIdentity: return _identity
