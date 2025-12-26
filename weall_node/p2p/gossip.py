#!/usr/bin/env python3
"""
weall_node/p2p/gossip.py
-----------------------

Outbound-first gossip + peer exchange loop.

Updated: includes capability advertisement and merges peer capabilities.

Goals:
- Works behind NAT (phones)
- No inbound requirements
- Resilient to churn
- No privileged nodes
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import List

import httpx

from weall_node.p2p.mesh import get_registry, get_identity
from weall_node.p2p.caps import build_self_capabilities

log = logging.getLogger(__name__)


class GossipLoop:
    def __init__(self) -> None:
        self.interval = int(os.getenv("WEALL_P2P_GOSSIP_INTERVAL_SEC", "30"))
        self.fanout = int(os.getenv("WEALL_P2P_PEX_FANOUT", "4"))
        self.max_peers = int(os.getenv("WEALL_P2P_MAX_PEERS", "256"))
        self.timeout = float(os.getenv("WEALL_P2P_HTTP_TIMEOUT_SEC", "2.5"))
        self.bootstrap = self._parse_bootstrap()
        self._stop = threading.Event()

        # Optional "self address" to announce (helps other peers learn a stable URL)
        # Example: export WEALL_P2P_SELF_ADDR="https://api.weallprotocol.xyz"
        self.self_addr = os.getenv("WEALL_P2P_SELF_ADDR", "").strip().rstrip("/")

        # Capabilities advertised in announce meta
        self.self_caps = build_self_capabilities()

    def _parse_bootstrap(self) -> List[str]:
        raw = os.getenv("WEALL_P2P_BOOTSTRAP", "")
        return [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        log.info("[p2p] gossip loop started (interval=%ss)", self.interval)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                log.exception("[p2p] gossip tick failed")
            self._stop.wait(self.interval)

    def _tick(self) -> None:
        reg = get_registry()
        ident = get_identity()

        peers = list(reg.list_peers().values())
        targets = []

        if peers:
            random.shuffle(peers)
            targets.extend(peers[: self.fanout])

        # Always sprinkle in bootstrap peers
        for addr in self.bootstrap:
            targets.append(type("Tmp", (), {"node_id": None, "addr": addr}))

        seen = set()
        for peer in targets:
            addr = str(peer.addr).rstrip("/")
            if not addr or addr in seen:
                continue
            seen.add(addr)
            self._contact_peer(addr, ident)

        reg.prune_to_max(self.max_peers)

    def _contact_peer(self, addr: str, ident) -> None:
        url = addr.rstrip("/") + "/p2p"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                # announce (include capabilities)
                meta = {"caps": self.self_caps}
                announce_addr = self.self_addr or addr  # if self_addr not provided, keep "addr" field usable
                hello = ident.signed_hello(announce_addr, meta=meta)

                r = client.post(url + "/announce", json=hello)
                r.raise_for_status()

                # fetch peers
                r = client.get(url + "/peers")
                r.raise_for_status()
                data = r.json()
                self._merge_peers(data)

        except Exception as e:
            log.debug("[p2p] peer %s failed: %s", addr, e)

    def _merge_peers(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        peers = payload.get("peers")
        if not isinstance(peers, list):
            return

        reg = get_registry()
        for rec in peers:
            if not isinstance(rec, dict):
                continue
            node_id = rec.get("node_id")
            addr = rec.get("addr")
            meta = rec.get("meta")
            if node_id and addr:
                # Merge meta (including caps) if present
                reg.upsert_peer(node_id=str(node_id), addr=str(addr), meta=meta if isinstance(meta, dict) else {})
