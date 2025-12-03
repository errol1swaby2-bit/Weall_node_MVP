"""
weall_node/p2p/sync_manager.py
--------------------------------------------------
Lightweight IPFS pubsub bridge for WeAll peer-to-peer sync.
Publishes and subscribes to "weall-sync" topic for block/epoch updates.
"""

import asyncio
import json
import threading
from typing import Callable, Optional, Dict, Any

try:
    import ipfshttpclient  # type: ignore
except Exception:
    ipfshttpclient = None


class SyncManager:
    def __init__(
        self, topic: str = "weall-sync", api_addr: str = "/dns/localhost/tcp/5001/http"
    ):
        self.topic = topic
        self.api_addr = api_addr
        self.client = None
        self.running = False
        self._listener_thread: Optional[threading.Thread] = None
        self.on_message: Optional[Callable[[Dict[str, Any]], None]] = None

    def connect(self) -> bool:
        if ipfshttpclient is None:
            print("[WARN] ipfshttpclient not installed; sync disabled.")
            return False
        try:
            self.client = ipfshttpclient.connect(self.api_addr)
            return True
        except Exception as e:
            print(f"[WARN] Failed to connect to IPFS API: {e}")
            return False

    # -----------------------------------------------------------
    # Publish / Subscribe
    # -----------------------------------------------------------
    def publish(self, payload: Dict[str, Any]):
        if not self.client and not self.connect():
            return False
        try:
            msg = json.dumps(payload)
            self.client.pubsub.publish(self.topic, msg.encode("utf-8"))
            return True
        except Exception as e:
            print(f"[WARN] Pubsub publish failed: {e}")
            return False

    def _listen_loop(self):
        if not self.client:
            return
        try:
            sub = self.client.pubsub.subscribe(self.topic)
            for msg in sub:
                try:
                    data = json.loads(msg["data"].decode("utf-8"))
                    if self.on_message:
                        self.on_message(data)
                except Exception:
                    continue
        except Exception as e:
            print(f"[WARN] pubsub subscribe failed: {e}")

    def start_listener(self, callback: Callable[[Dict[str, Any]], None]):
        """Start background listener thread."""
        if self.running:
            return
        self.on_message = callback
        self.running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop_listener(self):
        self.running = False
