"""
weall_node/api/p2p_overlay.py
--------------------------------------------------
Basic peer overlay API for WeAll Node.

Exposes:
- GET  /p2p/node       → local node identity (node_id, pub_hex)
- GET  /p2p/peers      → snapshot of known peers (from mesh registry)
- GET  /p2p/debug      → extended diagnostics (node + peers + executor.p2p)
- POST /p2p/announce   → accept a signed peer announcement
- POST /p2p/bootstrap  → send our own announcement to configured bootstrap URLs

Bootstrap configuration:
- Environment variable P2P_BOOTSTRAP may contain a comma-separated list of
  base URLs for other nodes, e.g.:

      export P2P_BOOTSTRAP="http://10.0.0.5:8000,http://10.0.0.6:8000"

  When you POST /p2p/bootstrap, this node will send a signed /p2p/announce
  to each of those URLs.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from cryptography.hazmat.primitives.asymmetric import ed25519

from ..settings import Settings
from ..p2p.mesh import init_p2p, get_registry, get_identity
from ..weall_executor import executor

# stdlib HTTP client so we don't add new deps
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

settings = Settings()
_registry, _identity = init_p2p(settings.ROOT_DIR)

router = APIRouter(prefix="/p2p", tags=["p2p"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PeerAnnounce(BaseModel):
    node_id: Optional[str] = Field(
        None,
        description="Peer node id; if omitted we derive from pub_hex.",
    )
    addr: Optional[str] = Field(
        None,
        description="Contact string for the peer (e.g. ws://host:8000 or node URL).",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form peer metadata (env, roles, etc.).",
    )
    ts: int = Field(..., description="Sender's timestamp (seconds since epoch).")
    nonce: str = Field(..., description="Random hex nonce to make each announce unique.")
    pub_hex: Optional[str] = Field(
        None,
        description="Ed25519 public key of the peer (hex). Required when signature is set.",
    )
    signature: Optional[str] = Field(
        None,
        description="Hex-encoded Ed25519 signature over 'node_id|addr|ts|nonce'.",
    )

    @validator("ts")
    def _ts_not_too_far_future(cls, v: int) -> int:
        # Allow up to 5 minutes clock skew into the future
        if v > int(time.time()) + 300:
            raise ValueError("timestamp is too far in the future")
        return v

    @validator("nonce")
    def _nonce_hex(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("nonce too short")
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_signature(payload: PeerAnnounce, derived_node_id: str) -> None:
    """
    Verify the Ed25519 signature if present.

    Raises HTTPException(400, ...) on failure.
    """
    if not payload.signature:
        # No signature provided → accept in dev / private contexts
        return
    if not payload.pub_hex:
        raise HTTPException(status_code=400, detail="pub_hex required when signature is set")

    try:
        pub_bytes = bytes.fromhex(payload.pub_hex)
        sig_bytes = bytes.fromhex(payload.signature)
        pub = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid pub_hex or signature encoding")

    message = f"{derived_node_id}|{payload.addr or ''}|{payload.ts}|{payload.nonce}".encode(
        "utf-8"
    )

    try:
        pub.verify(sig_bytes, message)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")


def _register_peer(node_id: str, addr: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insert the peer into the mesh registry and executor.p2p manager.
    """
    registry = get_registry()
    rec = registry.upsert_peer(node_id=node_id, addr=addr, meta=meta)

    # Mirror into executor.p2p so /api/health/p2p has something to show
    try:
        p2p = getattr(executor, "p2p", None)
        if p2p is not None:
            p2p.add_peer(node_id)
    except Exception:
        # Non-fatal
        pass

    return rec.to_dict()


def _get_bootstrap_urls() -> List[str]:
    """
    Return a list of configured bootstrap base URLs from settings or env.

    We look for:
      - settings.P2P_BOOTSTRAP (if present)
      - env P2P_BOOTSTRAP
    """
    raw = getattr(settings, "P2P_BOOTSTRAP", "") or os.getenv("P2P_BOOTSTRAP", "")
    if not raw:
        return []
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return urls


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/node")
def get_local_node():
    """
    Return this node's identity info for diagnostics and bootstrap.
    """
    ident = get_identity()
    return {
        "ok": True,
        "node_id": ident.node_id,
        "pub_hex": ident.pub_hex,
    }


@router.get("/peers")
def list_peers():
    """
    Return a snapshot of known peers from the mesh registry.
    """
    registry = get_registry()
    peers = registry.snapshot()
    return {"ok": True, "peers": peers, "count": len(peers)}


@router.get("/debug")
def debug_p2p():
    """
    Extended P2P diagnostics for developers.

    Returns:
        {
          "ok": true,
          "node": { "node_id": "...", "pub_hex": "..." },
          "registry": [ {node_id, addr, last_seen, meta}, ... ],
          "executor_peers": ["node:....", ...],
          "executor_peer_count": 0
        }
    """
    ident = get_identity()
    registry = get_registry()
    reg_snapshot = registry.snapshot()

    exec_peer_ids: List[str] = []
    try:
        p2p = getattr(executor, "p2p", None)
        if p2p is not None:
            getter = getattr(p2p, "get_peer_list", None)
            if callable(getter):
                exec_peer_ids = list(getter())
    except Exception:
        exec_peer_ids = []

    return {
        "ok": True,
        "node": {
            "node_id": ident.node_id,
            "pub_hex": ident.pub_hex,
        },
        "registry": reg_snapshot,
        "executor_peers": exec_peer_ids,
        "executor_peer_count": len(exec_peer_ids),
    }


@router.post("/announce")
def announce_peer(payload: PeerAnnounce):
    """
    Accept a peer announcement and store it in the registry.

    Expected payload shape (PeerAnnounce):
      - node_id: optional; if omitted we use 'node:' + pub_hex[:12]
      - addr: connection info (URL, host:port, etc.)
      - meta: free-form metadata
      - ts, nonce: freshness + uniqueness
      - pub_hex, signature: optional; if present, we verify the signature
    """
    if not payload.node_id and not payload.pub_hex:
        raise HTTPException(
            status_code=400,
            detail="Either node_id or pub_hex must be provided",
        )

    # Derive canonical node_id from pub_hex if available
    node_id = payload.node_id
    if payload.pub_hex:
        node_id = f"node:{payload.pub_hex[:12]}"
    if not node_id:
        raise HTTPException(status_code=400, detail="Could not derive node_id")

    # Verify signature when provided
    _verify_signature(payload, derived_node_id=node_id)

    addr = payload.addr or ""
    meta = payload.meta or {}
    meta.setdefault("last_ts", payload.ts)

    rec_dict = _register_peer(node_id=node_id, addr=addr, meta=meta)
    return {"ok": True, "peer": rec_dict}


@router.post("/bootstrap")
def bootstrap_peers():
    """
    Send this node's signed announcement to all configured bootstrap URLs.

    P2P_BOOTSTRAP is a comma-separated list of base URLs, e.g.:

        http://10.0.0.5:8000,http://10.0.0.6:8000

    For each URL, we POST to <url>/p2p/announce with our signed payload.

    Returns a summary of successes/errors for each URL.
    """
    urls = _get_bootstrap_urls()
    if not urls:
        return {
            "ok": False,
            "error": "no_bootstrap_urls",
            "urls": [],
        }

    ident = get_identity()
    # Use our HTTP base address as addr if available; otherwise leave blank
    base_addr = os.getenv("P2P_SELF_ADDR", "")
    payload = ident.build_announce(addr=base_addr, meta={})

    results = []
    for base in urls:
        base = base.strip().rstrip("/")
        if not base:
            continue
        announce_url = f"{base}/p2p/announce"
        try:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            req = urlrequest.Request(
                announce_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlrequest.urlopen(req, timeout=3.0) as resp:
                # We don't care about body, but we read it to complete the request cleanly
                _ = resp.read()
            results.append({"url": base, "status": "ok"})
        except (HTTPError, URLError) as exc:
            results.append({"url": base, "status": "error", "error": str(exc)})
        except Exception as exc:
            results.append({"url": base, "status": "error", "error": f"unexpected: {exc}"})

    return {
        "ok": True,
        "results": results,
    }
