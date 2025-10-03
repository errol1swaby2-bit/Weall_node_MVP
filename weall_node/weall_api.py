#!/usr/bin/env python3
"""
WeAll Node API (FastAPI) — production-prep
- Access control via Proof-of-Humanity (PoH) NFTs
- CORS + security headers
- In-process rate limiting
- Request logging
- Prometheus metrics at /metrics
- Health endpoints: /healthz, /ready
- IPFS client lifecycle and pinning integrations (with storage wrapper)
- Peer health & orphan-rate gauges (stubs)
"""

import os, time, threading, contextlib, logging, pathlib
from typing import Callable
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ---- Executor instance ----
from weall_node.executor import WeAllExecutor
executor_instance = WeAllExecutor(auto_scheduler=True)

# ---- Routers & runtime imports (✅ fixed: import router objects directly) ----
from weall_node.api.chain import router as chain_router
from weall_node.api.pinning import router as pin_router
from weall_node.api.disputes import router as disputes_router
from weall_node.api.content import router as posts_router
from weall_node.api.governance import router as gov_router
from weall_node.api.ledger import router as ledger_router
from weall_node.api.messaging import router as messaging_router
from weall_node.api.poh import router as poh_router
from weall_node.api.reputation import router as rep_router
from weall_node.api.sync import router as sync_router
from weall_node.api.treasury import router as treasury_router
from weall_node.api.verification import router as verification_router
from weall_node.api.validators import router as validators_router
from weall_node.api.operators import router as operators_router

from weall_node.settings import Settings as S
from weall_node.weall_runtime.wallet import has_nft   # 🔑 PoH NFT check
from weall_node.weall_runtime import poh              # 🔑 process tier2 queue
from weall_node.weall_runtime.storage import set_client, get_client as get_ipfs_client
from weall_node.ipfs.client import IPFSClient

# ---- FastAPI app ----
app = FastAPI(
    title="WeAll Node API",
    version="0.3.1",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---- Mount frontend ----
frontend_path = pathlib.Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/frontend", StaticFiles(directory=str(frontend_path)), name="frontend")

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in S.ALLOWED_ORIGINS.split(',') if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---- Logging ----
logger = logging.getLogger(S.SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

# ---- Error handlers ----
@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": exc.errors()}, status_code=422)

@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)

# ---- Middlewares ----
@app.middleware("http")
async def access_log(request: Request, call_next: Callable):
    start = time.time()
    response = await call_next(request)
    dur_ms = int((time.time() - start) * 1000)
    logger.info("%s %s %s %dms", request.method, request.url.path, response.status_code, dur_ms)
    return response

@app.middleware("http")
async def security_and_auth(request: Request, call_next: Callable):
    """
    Enforces access control:
    - Public: /, /docs, /openapi.json, /healthz, /ready, /metrics
    - Protected: everything else requires Level 1+ PoH NFT
    """
    open_paths = {
        "/", "/docs", "/openapi.json", "/healthz", "/ready", "/metrics",
        "/verification/request",
        "/verification/status",
        "/content/upload",
        # PoH bootstrap endpoints
        "/poh/request-tier1",
        "/poh/verify-tier1",
    }

    if request.url.path.startswith("/poh/status"):
        return await call_next(request)

    if request.url.path not in open_paths:
        user_id = request.headers.get("X-User-ID")
        if not user_id or not has_nft(user_id, "PoH", min_level=1):
            return JSONResponse({"detail": "Unauthorized - PoH Level 1 NFT required"}, status_code=401)

    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' data:"
    return response

# ---- Rate limiting ----
_BUCKET = {"win": S.RATE_WINDOW, "lim": S.RATE_LIMIT, "ips": {}}
@app.middleware("http")
async def rate_limit(request: Request, call_next: Callable):
    now = int(time.time())
    ip = request.client.host if request.client else "unknown"
    B = _BUCKET
    ent = B["ips"].setdefault(ip, {"ts": now, "n": 0})
    if now - ent["ts"] >= B["win"]:
        ent["ts"] = now
        ent["n"] = 0
    ent["n"] += 1
    if ent["n"] > B["lim"]:
        return JSONResponse({"detail": "Rate limit"}, status_code=429)
    return await call_next(request)

# ---- Prometheus metrics ----
REQ_COUNT = Counter("weall_http_requests_total", "HTTP requests", ["method","path","code"])
REQ_LATENCY = Histogram("weall_http_request_duration_seconds", "Request latency", ["path"])
PEER_COUNT = Gauge("weall_peer_count", "Current p2p peer count")
ORPHAN_RATE = Gauge("weall_orphan_rate", "Estimated orphan rate (0..1)")

@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

# ---- Health ----
@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"

@app.get("/ready")
async def ready():
    return {"service": S.SERVICE_NAME, "ready": True}

@app.get("/")
async def root():
    return {"status": "ok"}

# ---- Routers ----
app.include_router(chain_router)
app.include_router(posts_router)
app.include_router(gov_router)
app.include_router(ledger_router)
app.include_router(messaging_router)
app.include_router(poh_router)
app.include_router(rep_router)
app.include_router(disputes_router)
app.include_router(pin_router)
app.include_router(sync_router)
app.include_router(treasury_router)
app.include_router(verification_router)
app.include_router(validators_router)
app.include_router(operators_router)

# ---- Background worker ----
_RUNNING = True
def _replicate_worker():
    while _RUNNING:
        def _cid_exists(cid: str) -> bool:
            try:
                c = get_ipfs_client()
                if not c:
                    return False
                info = c.get_info(cid)
                return info.get("ok", False)
            except Exception:
                return False

        try:
            poh.process_tier2_queue(_cid_exists)
        except Exception as e:
            logger.debug("Tier2 queue processing skipped: %s", e)

        time.sleep(5)

@app.on_event("startup")
async def _startup():
    try:
        client = IPFSClient(S.IPFS_ADDR)
        set_client(client)
    except Exception as e:
        logger.warning("IPFS client not available: %s", e)
        set_client(None)
    threading.Thread(target=_replicate_worker, daemon=True).start()

@app.on_event("shutdown")
async def _shutdown():
    global _RUNNING
    _RUNNING = False
    with contextlib.suppress(Exception):
        set_client(None)
