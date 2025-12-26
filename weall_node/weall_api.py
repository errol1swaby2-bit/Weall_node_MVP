from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from weall_node.settings import settings
from weall_node.p2p.mesh import init_p2p
from weall_node.p2p.gossip import GossipLoop
from weall_node.api import p2p_overlay

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="WeAll Node API")

    # CORS — tighten in prod if needed
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize P2P
    repo_root = os.getcwd()
    init_p2p(repo_root)

    if settings.P2P_ENABLED:
        gossip = GossipLoop()
        gossip.start()

    # Routers
    app.include_router(p2p_overlay.router)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
