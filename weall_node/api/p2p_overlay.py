from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from weall_node.p2p.mesh import get_registry, get_identity
from weall_node.p2p.caps import build_self_capabilities, supports_purpose

router = APIRouter(prefix="/p2p", tags=["p2p"])


def _parse_bootstrap() -> List[str]:
    raw = os.getenv("WEALL_P2P_BOOTSTRAP", "")
    out: List[str] = []
    for part in raw.split(","):
        p = part.strip().rstrip("/")
        if p:
            out.append(p)
    return out


def _normalize_peer_list(peers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for p in peers or []:
        if not isinstance(p, dict):
            continue
        addr = str(p.get("addr") or "").rstrip("/")
        nid = str(p.get("node_id") or "")
        if not addr or not nid:
            continue
        key = (nid, addr)
        if key in seen:
            continue
        seen.add(key)
        p2 = dict(p)
        p2["addr"] = addr
        out.append(p2)
    return out


def _mix_pick(scored: List[Dict[str, Any]], k: int, top_frac: float = 0.6) -> List[Dict[str, Any]]:
    if not scored:
        return []
    k = max(3, min(k, 30))
    k = min(k, len(scored))

    top_n = max(1, int(round(k * max(0.0, min(1.0, top_frac)))))
    picked = list(scored[:top_n])

    rest = scored[top_n:]
    if rest and len(picked) < k:
        picked.extend(random.sample(rest, min(len(rest), k - len(picked))))

    return _normalize_peer_list(picked)


@router.get("/node")
def node_info() -> Dict[str, Any]:
    ident = get_identity()
    return {
        "node_id": ident.node_id,
        "pub_hex": ident.pub_hex,
        "ts": int(time.time()),
    }


@router.get("/ping")
def ping() -> Dict[str, Any]:
    ident = get_identity()
    return {"ok": True, "node_id": ident.node_id, "ts": int(time.time())}


@router.get("/capabilities")
def capabilities() -> Dict[str, Any]:
    """
    Returns this node's advertised capabilities (for debugging + operator UX).
    """
    return {"caps": build_self_capabilities(), "ts": int(time.time())}


@router.get("/client_config")
def client_config() -> Dict[str, Any]:
    seeds = _parse_bootstrap()

    pick_k = int(os.getenv("WEALL_CLIENT_PICK_K", "10"))
    refresh_sec = int(os.getenv("WEALL_CLIENT_REFRESH_SEC", "180"))
    timeout_ms = int(os.getenv("WEALL_CLIENT_TIMEOUT_MS", "2500"))
    fail_cooldown_sec = int(os.getenv("WEALL_CLIENT_FAIL_COOLDOWN_SEC", "60"))
    max_pool = int(os.getenv("WEALL_CLIENT_MAX_POOL", "64"))

    # Purpose defaults: clients can ask for feed/upload/governance/webrtc
    return {
        "seeds": seeds,
        "rules": {
            "pick_k": max(3, min(pick_k, 30)),
            "refresh_interval_sec": max(30, min(refresh_sec, 3600)),
            "timeout_ms": max(500, min(timeout_ms, 15000)),
            "fail_cooldown_sec": max(5, min(fail_cooldown_sec, 3600)),
            "max_pool": max(8, min(max_pool, 256)),
            "mix": {"top_frac": 0.6, "random_frac": 0.4},
            "purposes": ["feed", "upload", "governance", "webrtc"],
        },
        "ts": int(time.time()),
    }


@router.get("/peers")
def list_peers() -> Dict[str, Any]:
    reg = get_registry()
    return {"peers": reg.snapshot_scored(), "ts": int(time.time())}


@router.get("/peers/top")
def top_peers(limit: int = 50) -> Dict[str, Any]:
    reg = get_registry()
    peers = reg.snapshot_scored()[: max(1, min(limit, 500))]
    return {"peers": peers, "ts": int(time.time())}


@router.get("/peers/pick")
def pick_peers(k: int = 10) -> Dict[str, Any]:
    reg = get_registry()
    scored = reg.snapshot_scored()
    peers = _mix_pick(scored, k=k, top_frac=0.6)
    return {"peers": peers, "ts": int(time.time())}


@router.get("/peers/pick_for")
def pick_peers_for(purpose: str = "governance", k: int = 10) -> Dict[str, Any]:
    """
    Purpose-aware peer selection.

    purpose:
      - feed: prefer video_gateway/hls operators
      - upload: prefer operators + ipfs_pin (optional) and good bandwidth
      - governance: any reliable node is fine
      - webrtc: prefer nodes that support webrtc (signaling)
    """
    purpose = (purpose or "").strip().lower()
    if purpose not in {"feed", "upload", "governance", "webrtc"}:
        raise HTTPException(400, "unknown purpose")

    reg = get_registry()
    scored = reg.snapshot_scored()

    # Filter to peers that claim they support this purpose.
    filtered = [p for p in scored if supports_purpose(p.get("meta") or {}, purpose)]

    # If no one advertises it yet, fall back to generic pick (do not strand clients).
    if not filtered:
        filtered = scored

    # For feed, bias toward "video_gateway" / "hls"
    if purpose == "feed":
        def _feed_rank(p: Dict[str, Any]) -> tuple:
            meta = p.get("meta") or {}
            caps = (meta.get("caps") or {}) if isinstance(meta, dict) else {}
            vg = 1 if bool(caps.get("video_gateway")) else 0
            hls = 1 if bool(caps.get("hls")) else 0
            score = float(p.get("score") or 0.0)
            return (vg, hls, score)
        filtered = sorted(filtered, key=_feed_rank, reverse=True)

    # For upload, bias toward operator nodes with higher bandwidth_kbps
    if purpose == "upload":
        def _up_rank(p: Dict[str, Any]) -> tuple:
            meta = p.get("meta") or {}
            caps = (meta.get("caps") or {}) if isinstance(meta, dict) else {}
            op = 1 if bool(caps.get("operator")) else 0
            pin = 1 if bool(caps.get("ipfs_pin")) else 0
            bw = int(caps.get("bandwidth_kbps") or 0)
            score = float(p.get("score") or 0.0)
            return (op, pin, bw, score)
        filtered = sorted(filtered, key=_up_rank, reverse=True)

    # For webrtc, bias toward nodes that claim it
    if purpose == "webrtc":
        # supports_purpose already filtered; keep score order
        pass

    peers = _mix_pick(filtered, k=k, top_frac=0.7)
    return {"peers": peers, "purpose": purpose, "ts": int(time.time())}


@router.post("/announce")
def announce(payload: Dict[str, Any]) -> Dict[str, Any]:
    ident = get_identity()
    reg = get_registry()

    required = {"node_id", "addr", "ts", "nonce", "signature", "pub_hex"}
    if not required.issubset(payload.keys()):
        raise HTTPException(400, "missing fields")

    node_id = str(payload["node_id"])
    addr = str(payload["addr"]).rstrip("/")
    ts = int(payload["ts"])
    nonce = str(payload["nonce"])
    sig = str(payload["signature"])
    pub_hex = str(payload["pub_hex"])
    meta = payload.get("meta") or {}

    if not node_id or not addr:
        raise HTTPException(400, "invalid node_id/addr")

    msg = f"{node_id}|{addr}|{ts}|{nonce}".encode("utf-8")
    if not ident.verify(msg, sig, pub_hex):
        raise HTTPException(401, "bad signature")

    reg.upsert_peer(node_id=node_id, addr=addr, meta=meta if isinstance(meta, dict) else {})
    return {"ok": True, "ts": int(time.time())}
