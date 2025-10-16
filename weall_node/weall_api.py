#!/usr/bin/env python3
"""
WeAll Node API (FastAPI)
------------------------
Primary API interface for the WeAll Protocol MVP.

Features:
- Health / metrics
- Chain + ledger
- Users / PoH onboarding stubs
- Content: posts, comments
- Disputes (init/list + stubs for vote/resolve)
- Governance (list, vote)
- Reputation (get/increment)
- P2P announce / peers / handshake + WebSocket relay
- IPFS uploads
- Node diagnostics
- Static frontend

HTTPS:
- Set WEALL_FORCE_HTTPS=1 to redirect HTTP→HTTPS and send HSTS.
- Start uvicorn with --ssl-certfile/--ssl-keyfile to enable TLS.
"""

from __future__ import annotations
import os, time, json, base64, asyncio, pathlib, logging
from typing import Optional

import ipfshttpclient
import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Core executor + PoH requirements
from weall_node.weall_executor import WeAllExecutor, POH_REQUIREMENTS

# P2P mesh utilities
from weall_node.p2p.mesh import (
    init_mesh, Peer, verify_signature
)

# ------------------------------------------------------------------------------
# App bootstrap
# ------------------------------------------------------------------------------

app = FastAPI(title="WeAll Node API", version="0.9.2", docs_url="/docs", redoc_url="/redoc")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("weall_api")

# CORS (open for MVP)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Observability
REQ_COUNT = Counter("weall_requests_total", "Total API requests", ["method", "endpoint"])
REQ_LAT   = Histogram("weall_request_latency_seconds", "Request latency (s)", ["endpoint"])
CHAIN_ORPHANS = Gauge("weall_chain_orphan_blocks", "Orphan block count")

FORCE_HTTPS = os.environ.get("WEALL_FORCE_HTTPS", "0") == "1"

@app.middleware("http")
async def metrics_and_security(request: Request, call_next):
    # Optional HTTP→HTTPS redirect
    if FORCE_HTTPS and request.url.scheme != "https":
        # preserve path + query
        https_url = str(request.url).replace("http://", "https://", 1)
        return RedirectResponse(url=https_url, status_code=307)

    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        logger.exception("Request failed: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # Metrics
    try:
        REQ_COUNT.labels(request.method, request.url.path).inc()
        REQ_LAT.labels(request.url.path).observe(time.time() - start)
    except Exception:
        pass

    # Security headers
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if FORCE_HTTPS and request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# ------------------------------------------------------------------------------
# IPFS (safe-fail)
# ------------------------------------------------------------------------------
try:
    IPFS = ipfshttpclient.connect("/ip4/127.0.0.1/tcp/5001")
    logger.info("[IPFS] Connected OK")
except Exception as e:
    IPFS = None
    logger.warning(f"[IPFS] connection failed: {e}")

# ------------------------------------------------------------------------------
# Executor + Mesh
# ------------------------------------------------------------------------------
EXEC = WeAllExecutor(
    dsl_file="weall_dsl_v0.5.yaml",
    poh_requirements=POH_REQUIREMENTS,
)
# repo root = two parents up from this file
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY, IDENTITY = init_mesh(REPO_ROOT)

# ------------------------------------------------------------------------------
# Health & metrics
# ------------------------------------------------------------------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True, "uptime": time.time() - EXEC.start_ts}

@app.get("/ready")
async def ready():
    return {"ok": True, "chain_blocks": len(EXEC.chain.blocks)}

@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# ------------------------------------------------------------------------------
# Chain
# ------------------------------------------------------------------------------
@app.get("/chain/blocks")
async def get_chain():
    return EXEC.chain.blocks

@app.get("/chain/mempool")
async def get_mempool():
    return EXEC.chain.get_mempool()

@app.post("/chain/finalize")
async def finalize_chain(req: Request):
    data = await req.json()
    return EXEC.finalize_block(data.get("user_id"))

# ------------------------------------------------------------------------------
# Ledger
# ------------------------------------------------------------------------------
@app.post("/ledger/create_account")
async def ledger_create(req: Request):
    data = await req.json()
    return EXEC.ledger.create_account(data["user_id"])

@app.post("/ledger/deposit")
async def ledger_deposit(req: Request):
    data = await req.json()
    return EXEC.ledger.deposit(data["user_id"], data["amount"])

@app.post("/ledger/transfer")
async def ledger_transfer(req: Request):
    data = await req.json()
    return EXEC.ledger.transfer(data["from_user"], data["to_user"], data["amount"])

@app.get("/ledger/balance/{user_id}")
async def ledger_balance(user_id: str):
    """LedgerState has .balance(); fallback to accounts dict for legacy."""
    try:
        balance = EXEC.ledger.balance(user_id)
    except AttributeError:
        balance = EXEC.ledger.accounts.get(user_id, 0.0)
    return {"user_id": user_id, "balance": balance}

# ------------------------------------------------------------------------------
# Users / PoH (minimal stubs)
# ------------------------------------------------------------------------------
@app.post("/register")
async def register(req: Request):
    data = await req.json()
    res = EXEC.register_user(data.get("user_id"), int(data.get("poh_level", 1)))
    if not res.get("ok"):
        return JSONResponse({"detail": res.get("error", "error")}, status_code=400)
    return {"ok": True}

@app.post("/poh/request-tier1")
async def poh_request_tier1(req: Request):
    d = await req.json()
    return EXEC.request_tier1(d["user"], d["email"])

@app.post("/poh/tier2")
async def poh_tier2(req: Request):
    d = await req.json()
    try:
        return EXEC.verify_tier2(d["user"], d["evidence"])
    except AttributeError:
        return {"ok": True, "tier": 2, "message": "Evidence received (stub)"}

@app.post("/poh/tier3/request")
async def poh_tier3_request(req: Request):
    d = await req.json()
    uid = d.get("user_id")
    EXEC.state.setdefault("governance_log", []).append(
        {"type": "tier3_request", "user": uid, "ts": time.time(), "phase": "A_pending"}
    )
    EXEC.save_state()
    return {"ok": True, "user": uid, "phase": "A_pending"}

@app.post("/poh/video/initiate")
async def poh_video_initiate(req: Request):
    d = await req.json()
    founder, target = d.get("founder_id"), d.get("target_user")
    token_res = await p2p_handshake(Request(scope={"type": "http"}))
    token = token_res["token"]
    return {
        "ok": True,
        "session_id": token,
        "join_urls": {
            "founder":  f"/verify.html?token={token}&role=founder&uid={founder}",
            "candidate": f"/verify.html?token={token}&role=candidate&uid={target}",
        },
    }

@app.post("/poh/tier3/founder_approve")
async def poh_founder_approve(req: Request):
    d = await req.json()
    EXEC.state.setdefault("governance_log", []).append(
        {"type": "tier3_founder_approve", "founder": d.get("founder_id"),
         "user": d.get("target_user"), "ts": time.time(), "phase": "B_pending"}
    )
    EXEC.save_state()
    return {"ok": True, "phase": "B_pending"}

@app.get("/poh/tier3/status/{user_id}")
async def poh_tier3_status(user_id: str):
    u = EXEC.state.get("users", {}).get(user_id) or {}
    return {
        "user": user_id,
        "poh_level": int(u.get("poh_level", 0)),
        "epoch": EXEC.current_epoch,
        "pending": [e for e in EXEC.state.get("governance_log", []) if e.get("user") == user_id][-5:],
    }

@app.get("/poh/tier3/nft/{user_id}")
async def poh_tier3_nft(user_id: str):
    u = EXEC.state.get("users", {}).get(user_id) or {}
    if int(u.get("poh_level", 0)) < 3:
        return JSONResponse({"ok": False, "error": "not_tier3"}, status_code=400)
    nft = {
        "kind": "weall_tier3_badge",
        "user": user_id,
        "issued": int(time.time()),
        "sig": IDENTITY.sign(f"tier3|{user_id}".encode()),
    }
    return {"ok": True, "nft": nft}

# ------------------------------------------------------------------------------
# Messaging
# ------------------------------------------------------------------------------
@app.post("/messaging/send")
async def messaging_send(req: Request):
    d = await req.json()
    return EXEC.send_message(d["from_user"], d["to_user"], d["message"])

@app.get("/messaging/inbox/{user_id}")
async def messaging_inbox(user_id: str):
    return {"user_id": user_id, "messages": EXEC.read_messages(user_id)}

# ------------------------------------------------------------------------------
# Content: posts + comments
# ------------------------------------------------------------------------------
@app.get("/show_posts")
async def show_posts():
    """Return posts dict; enrich with media_url if ipfs_cid present."""
    posts = EXEC.state.get("posts", {})
    if posts and IPFS is not None:
        # Gateway runs at 127.0.0.1:8080 by default
        for p in posts.values():
            cid = p.get("ipfs_cid")
            if cid:
                p["media_url"] = f"http://127.0.0.1:8080/ipfs/{cid}"
    return posts

@app.post("/post")
async def create_post(req: Request):
    d = await req.json()
    res = EXEC.create_post(d["user_id"], d["content"], d.get("tags", []), ipfs_cid=d.get("ipfs_cid"))
    if not res.get("ok"):
        return JSONResponse({"detail": res.get("error", "error")}, status_code=400)
    return res

@app.post("/comment")
async def create_comment(req: Request):
    d = await req.json()
    res = EXEC.create_comment(d["user_id"], int(d["post_id"]), d["content"])
    if not res.get("ok"):
        return JSONResponse({"detail": res.get("error", "error")}, status_code=400)
    return res

# ------------------------------------------------------------------------------
# Disputes (MVP)
# ------------------------------------------------------------------------------
@app.post("/disputes/initiate")
async def disputes_initiate(req: Request):
    d = await req.json()
    dispute = {
        "id": len(EXEC.state.setdefault("disputes", [])),
        "user_id": d["user_id"],
        "post_id": d["post_id"],
        "reason": d.get("reason", ""),
        "evidence": d.get("evidence"),
        "status": "pending",
        "ts": time.time(),
    }
    EXEC.state["disputes"].append(dispute)
    EXEC.save_state()
    return {"ok": True, "dispute": dispute}

@app.get("/disputes/list")
async def disputes_list():
    return EXEC.state.get("disputes", [])

@app.post("/disputes/vote")
async def disputes_vote(req: Request):
    """Stub: record juror votes; no tally logic yet."""
    d = await req.json()
    EXEC.state.setdefault("dispute_votes", []).append(
        {"dispute_id": int(d["dispute_id"]), "juror": d["juror_id"], "vote": d["vote"], "ts": time.time()}
    )
    EXEC.save_state()
    return {"ok": True}

@app.post("/disputes/resolve")
async def disputes_resolve(req: Request):
    """Stub: set dispute status; in future enforce penalties/rewards."""
    d = await req.json()
    disputes = EXEC.state.get("disputes", [])
    idx = int(d["dispute_id"])
    if 0 <= idx < len(disputes):
        disputes[idx]["status"] = d.get("status", "resolved")
        EXEC.save_state()
        return {"ok": True, "dispute": disputes[idx]}
    return JSONResponse({"ok": False, "error": "invalid_dispute_id"}, status_code=400)

# ------------------------------------------------------------------------------
# Reputation
# ------------------------------------------------------------------------------
@app.get("/reputation/{user_id}")
async def reputation_get(user_id: str):
    score = 0
    rep = getattr(EXEC, "reputation", None)
    if isinstance(rep, dict):
        score = rep.get(user_id, 0)
    return {"user_id": user_id, "score": score}

@app.post("/reputation/increment")
async def reputation_increment(req: Request):
    d = await req.json()
    user = d["user_id"]
    amount = float(d.get("amount", 1))
    if not hasattr(EXEC, "reputation") or not isinstance(EXEC.reputation, dict):
        EXEC.reputation = {}
    EXEC.reputation[user] = EXEC.reputation.get(user, 0) + amount
    EXEC.save_state()
    return {"ok": True, "new_score": EXEC.reputation[user]}

# ------------------------------------------------------------------------------
# Governance
# ------------------------------------------------------------------------------
@app.get("/governance/proposals")
async def governance_list():
    try:
        return EXEC.list_proposals()
    except Exception:
        return getattr(EXEC.governance, "proposals", {})

@app.post("/governance/vote")
async def governance_vote(req: Request):
    d = await req.json()
    return EXEC.vote_on_proposal(d["user"], int(d["proposal_id"]), d["vote"])

# ------------------------------------------------------------------------------
# Epoch / Node diagnostics
# ------------------------------------------------------------------------------
@app.get("/epoch/status")
async def epoch_status():
    return {
        "epoch": EXEC.current_epoch,
        "validators": len(EXEC.state.get("validators", {})),
        "active_jurors": len(EXEC.state.get("jurors", {})),
        "treasury_balance": getattr(EXEC, "treasury_balance", 0),
    }

@app.get("/node/status")
async def node_status():
    peers = REGISTRY.list_peers()
    return {
        "ok": True,
        "node_id": IDENTITY.node_id,
        "peer_count": len(peers),
        "chain_height": len(EXEC.chain.blocks),
        "user_count": len(EXEC.state.get("users", {})),
        "posts": len(EXEC.state.get("posts", {})),
    }

# ------------------------------------------------------------------------------
# IPFS uploads
# ------------------------------------------------------------------------------
@app.post("/ipfs/add")
async def ipfs_add(req: Request):
    if IPFS is None:
        return JSONResponse({"ok": False, "error": "IPFS not connected"}, status_code=500)
    data = await req.body()
    cid = IPFS.add_bytes(data)
    return {"ok": True, "cid": cid}

# ------------------------------------------------------------------------------
# P2P: announce / peers / ping / sign / status
# ------------------------------------------------------------------------------
@app.post("/p2p/announce")
async def p2p_announce(req: Request):
    data = await req.json()
    pub = data.get("public_key") or ""
    url = data.get("url") or ""
    ts = int(data.get("ts") or 0)
    ttl = int(data.get("ttl") or 900)
    nonce = data.get("nonce") or ""
    sig = data.get("signature") or ""

    if not (pub and url and sig and ts and nonce):
        return JSONResponse({"ok": False, "error": "missing_fields"}, status_code=400)

    # replay & clock skew
    if REGISTRY.nonce_seen(nonce):
        return JSONResponse({"ok": False, "error": "replay"}, status_code=400)
    if abs(time.time() - ts) > 600:
        return JSONResponse({"ok": False, "error": "ts_out_of_range"}, status_code=400)

    message = f"{pub}|{url}|{ts}|{nonce}".encode()
    if not verify_signature(pub, message, sig):
        return JSONResponse({"ok": False, "error": "bad_signature"}, status_code=400)

    node_id = data.get("node_id") or pub[:16]
    p = Peer(
        node_id=node_id,
        public_key=pub,
        url=url,
        addrs=data.get("addrs", []),
        capabilities=data.get("capabilities", []),
        ttl=ttl,
    )
    p.last_seen = time.time()
    REGISTRY.upsert_peer(p)
    return {"ok": True, "node_id": node_id}

@app.get("/p2p/peers")
async def p2p_peers():
    return {"ok": True, "self": {"node_id": IDENTITY.node_id, "public_key": IDENTITY.pub_hex}, "peers": REGISTRY.list_peers()}

@app.get("/p2p/ping")
async def p2p_ping():
    return {"ok": True, "ts": int(time.time()), "node_id": IDENTITY.node_id}

@app.post("/p2p/sign")
async def p2p_sign(req: Request):
    d = await req.json()
    msg = (d.get("message") or "").encode()
    if not msg:
        return JSONResponse({"ok": False, "error": "missing_message"}, status_code=400)
    sig = IDENTITY.sign(msg)
    return {"ok": True, "node_id": IDENTITY.node_id, "public_key": IDENTITY.pub_hex, "signature": sig}

@app.get("/p2p/status")
async def p2p_status():
    peers = REGISTRY.list_peers()
    return {"ok": True, "node_id": IDENTITY.node_id, "peer_count": len(peers), "peers": peers}

# ------------------------------------------------------------------------------
# P2P: handshake + WebSocket signaling (opaque relay)
# ------------------------------------------------------------------------------
@app.post("/p2p/handshake")
async def p2p_handshake(_: Request):
    token = REGISTRY.new_token()
    secret = REGISTRY.new_secret()  # 32-byte key
    REGISTRY.set_room_secret(token, secret)
    return {"ok": True, "token": token, "ws": f"/ws/p2p/{token}", "secret_b64": base64.b64encode(secret).decode()}

@app.websocket("/ws/p2p/{token}")
async def ws_p2p(websocket: WebSocket, token: str):
    await websocket.accept()
    uid = None
    enc = False
    try:
        hello = await websocket.receive_json()
        if not (isinstance(hello, dict) and hello.get("action") == "hello" and "uid" in hello):
            await websocket.send_json({"error": "send hello first: {action:'hello', uid:'...'}"})
            await websocket.close()
            return
        uid = str(hello["uid"])
        enc = bool(hello.get("enc", False))
        if enc and not REGISTRY.get_room_secret(token):
            await websocket.send_json({"error": "no room secret; call /p2p/handshake first"})
            await websocket.close()
            return

        others = REGISTRY.join_room(token, uid, lambda payload: websocket.send_json(payload))
        await websocket.send_json({"status": "joined", "uid": uid, "others": others, "enc": enc})

        while True:
            msg = await websocket.receive_json()
            if enc:
                if not ("cipher" in msg and "nonce" in msg):
                    await websocket.send_json({"error": "encrypted room requires {cipher,nonce}"})
                    continue
                REGISTRY.relay(token, uid, {"from": uid, "cipher": msg["cipher"], "nonce": msg["nonce"]})
            else:
                dst = str(msg.get("to", ""))
                payload = {"from": uid, "data": msg.get("data")}
                REGISTRY.relay(token, uid, payload, dst=dst)
    except Exception:
        pass
    finally:
        try:
            REGISTRY.leave_room(token, uid)
        except Exception:
            pass
        await websocket.close()

# ------------------------------------------------------------------------------
# Static frontend
# ------------------------------------------------------------------------------
frontend_dir = pathlib.Path(__file__).resolve().parent / "frontend"
if frontend_dir.exists():
    # Serve index.html at "/"
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

logger.info("✅ WeAll API started — ready to serve requests.")
