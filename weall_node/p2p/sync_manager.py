"""
weall_node/p2p/sync_manager.py
--------------------------------------------------
Lightweight IPFS pubsub bridge for WeAll using the raw HTTP API.

Adjusted for kubo 0.39.0 which expects pubsub topics to be multibase
encoded (base64url with a leading "u" prefix).
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Callable, Optional, Dict, Any

import requests


def _addr_to_http(addr: Optional[str]) -> str:
    """
    Convert common IPFS_API styles to an HTTP URL.

    Examples:
        "/ip4/127.0.0.1/tcp/5001" -> "http://127.0.0.1:5001"
        "http://127.0.0.1:5001"   -> "http://127.0.0.1:5001"
        None                      -> "http://127.0.0.1:5001"
    """
    if not addr:
        return "http://127.0.0.1:5001"

    addr = addr.strip()

    if addr.startswith("http://") or addr.startswith("https://"):
        return addr.rstrip("/")

    if addr.startswith("/ip4/") and "/tcp/" in addr:
        try:
            _, _, host, _, port = addr.split("/", 4)
            return f"http://{host}:{port}"
        except Exception:
            pass

    return "http://127.0.0.1:5001"


def _encode_topic(topic: str) -> str:
    """
    Encode a topic string as multibase base64url, as expected by newer
    kubo pubsub HTTP endpoints.

    Scheme:
        - base64url(topic_bytes)
        - strip '=' padding
        - prefix with 'u' to signal base64url multibase
    """
    raw = topic.encode("utf-8")
    b64url = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return "u" + b64url


class SyncManager:
    """Thin wrapper around IPFS pubsub for WeAll via HTTP API."""

    def __init__(self, topic: str = "weall-sync", api_addr: str | None = None) -> None:
        self.topic = topic
        self.encoded_topic = _encode_topic(topic)
        self.api_addr = api_addr or "/ip4/127.0.0.1/tcp/5001"
        self.base_url = _addr_to_http(self.api_addr)
        self.running: bool = False
        self._listener_thread: Optional[threading.Thread] = None
        self.on_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Check connectivity to the IPFS daemon via /api/v0/version."""
        if self._connected:
            return True
        try:
            resp = requests.post(f"{self.base_url}/api/v0/version", timeout=3)
            if resp.ok:
                self._connected = True
                return True
        except Exception as e:  # pragma: no cover - environment dependent
            print(f"[WARN] Failed to connect to IPFS HTTP API at {self.base_url}: {e}")
        self._connected = False
        return False

    # ------------------------------------------------------------------
    # Publish / listen
    # ------------------------------------------------------------------

    def publish(self, payload: Dict[str, Any]) -> bool:
        """Publish a JSON payload on the sync topic via /pubsub/pub."""
        if not self.connect():
            return False
        try:
            data = json.dumps(payload, separators=(",", ":"))
            # pubsub/pub expects: arg=<topic>&arg=<data>
            params = [("arg", self.encoded_topic), ("arg", data)]
            resp = requests.post(
                f"{self.base_url}/api/v0/pubsub/pub",
                params=params,
                timeout=5,
            )
            if not resp.ok:
                print(f"[WARN] pubsub publish HTTP {resp.status_code}: {resp.text}")
                return False
            return True
        except Exception as e:  # pragma: no cover - environment dependent
            print(f"[WARN] pubsub publish failed: {e}")
            return False

    def _listen_loop(self) -> None:
        """Blocking loop that streams messages from /pubsub/sub."""
        if not self.connect():
            return
        try:
            resp = requests.post(
                f"{self.base_url}/api/v0/pubsub/sub",
                params={"arg": self.encoded_topic},
                stream=True,
                timeout=None,
            )
        except Exception as e:  # pragma: no cover - environment dependent
            print(f"[WARN] pubsub subscribe failed: {e}")
            return

        if not resp.ok:
            print(f"[WARN] pubsub subscribe HTTP {resp.status_code}: {resp.text}")
            return

        try:
            for line in resp.iter_lines():
                if not self.running:
                    break
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                    data_field = msg.get("data")
                    if isinstance(data_field, str):
                        try:
                            decoded = base64.b64decode(data_field)
                            payload = json.loads(decoded.decode("utf-8"))
                        except Exception:
                            payload = {"raw": msg}
                    else:
                        payload = {"raw": msg}

                    if self.on_message:
                        self.on_message(payload)
                except Exception as e:  # pragma: no cover - defensive
                    print(f"[WARN] pubsub message handler error: {e}")
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def start_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Start background listener thread (idempotent)."""
        if self.running:
            return
        self.on_message = callback
        self.running = True
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            name="weall-sync-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def stop_listener(self) -> None:
        self.running = False

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return a minimal status snapshot for /sync/status."""
        return {
            "ok": bool(self._connected),
            "topic": self.topic,
            "running": bool(self.running),
            "api_addr": self.api_addr,
        }
