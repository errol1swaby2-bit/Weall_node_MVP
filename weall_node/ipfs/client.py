"""
IPFS Client wrapper for WeAll Node
- Tries ipfshttpclient first
- Falls back to raw HTTP requests (compatible with Kubo 0.38+)
- Provides: add(path), add_bytes(data), cat(cid), pin(cid), get_info(cid)
- Global: set_client(...), get_client(), init_default_client()
"""

from __future__ import annotations
import os
import json
import time
from typing import Optional

# Optional ipfshttpclient (may fail with VersionMismatch on newer Kubo)
try:
    import ipfshttpclient  # type: ignore
except Exception:
    ipfshttpclient = None  # type: ignore

import requests  # lightweight HTTP fallback

# Global singleton
_client: "IPFSClient" | None = None


class _HTTPFallback:
    """
    Minimal HTTP wrapper for Kubo's /api/v0 endpoints.
    Works when ipfshttpclient can't connect due to version mismatch.
    """

    def __init__(self, api_addr: str = "http://127.0.0.1:5001"):
        # Normalize: accept raw host:port or full http://host:port
        if api_addr.startswith("/ip4/"):
            # Convert /ip4/127.0.0.1/tcp/5001 → http://127.0.0.1:5001
            parts = api_addr.split("/")
            host = parts[2]
            port = parts[4]
            api_addr = f"http://{host}:{port}"
        elif api_addr.startswith("127.") or api_addr.startswith("localhost"):
            api_addr = f"http://{api_addr}"
        self.base = api_addr.rstrip("/")

        # Quick sanity ping
        self._get("/api/v0/version")

    # --- HTTP helpers ---
    def _get(self, path: str, **params):
        r = requests.post(self.base + path, data=params, timeout=30)
        r.raise_for_status()
        return r

    def _post_files(self, path: str, files):
        r = requests.post(self.base + path, files=files, timeout=60)
        r.raise_for_status()
        return r

    # --- Operations ---
    def add(self, path: str):
        # streaming add: name must be "file"
        with open(path, "rb") as f:
            r = self._post_files(
                "/api/v0/add", files={"file": (os.path.basename(path), f)}
            )
        data = r.json()
        return data.get("Hash")

    def add_bytes(self, data: bytes):
        r = self._post_files("/api/v0/add", files={"file": ("blob", data)})
        data = r.json()
        return data.get("Hash")

    def cat(self, cid: str) -> bytes:
        r = self._get("/api/v0/cat", arg=cid)
        return r.content

    def pin_add(self, cid: str):
        r = self._get("/api/v0/pin/add", arg=cid)
        return r.json()

    def files_stat(self, path: str):
        r = self._get("/api/v0/files/stat", arg=path)
        return r.json()


class IPFSClient:
    """
    Unified client that wraps either ipfshttpclient or the HTTP fallback.
    """

    def __init__(self, addr: Optional[str] = None):
        # Allow env override
        addr = addr or os.getenv("IPFS_API", "/ip4/127.0.0.1/tcp/5001")

        self.mode = "http"
        self.client = None

        # First try ipfshttpclient if available
        if ipfshttpclient is not None:
            try:
                self.client = ipfshttpclient.connect(addr)
                # Touch the API to ensure it's live
                _ = self.client.version()
                self.mode = "py"
            except Exception:
                self.client = None  # fall back below

        # Fallback to HTTP wrapper
        if self.client is None:
            # Convert multiaddr or host:port into http URL
            http_addr = os.getenv("IPFS_HTTP_API", "http://127.0.0.1:5001")
            self.client = _HTTPFallback(http_addr)
            self.mode = "http"

    # --- Public methods ---

    def add(self, path: str):
        if self.mode == "py":
            res = self.client.add(path)  # type: ignore[attr-defined]
            if isinstance(res, dict):
                return res.get("Hash") or res.get("Cid", {}).get("/")

            if isinstance(res, list) and res:
                last = res[-1]
                return last.get("Hash") or last.get("Cid", {}).get("/")
            return res
        else:
            return self.client.add(path)  # HTTP

    def add_bytes(self, data: bytes):
        if self.mode == "py":
            return self.client.add_bytes(data)  # type: ignore[attr-defined]
        else:
            return self.client.add_bytes(data)  # HTTP

    def cat(self, cid: str) -> bytes:
        if self.mode == "py":
            return self.client.cat(cid)  # type: ignore[attr-defined]
        else:
            return self.client.cat(cid)  # HTTP

    def pin(self, cid: str):
        if self.mode == "py":
            # ipfshttpclient: client.pin.add(cid)
            return self.client.pin.add(cid)  # type: ignore[attr-defined]
        else:
            return self.client.pin_add(cid)  # HTTP

    def get_info(self, cid: str) -> dict:
        try:
            if self.mode == "py":
                # Some ipfshttpclient versions expose files.stat through commands
                stat = self.client.files.stat(f"/ipfs/{cid}")  # type: ignore[attr-defined]
                return {"ok": True, "cid": cid, "info": stat}
            else:
                stat = self.client.files_stat(f"/ipfs/{cid}")
                return {"ok": True, "cid": cid, "info": stat}
        except Exception as e:
            return {"ok": False, "cid": cid, "error": str(e)}


def set_client(client: IPFSClient | None):
    global _client
    _client = client


def get_client() -> IPFSClient | None:
    return _client


def init_default_client(force: bool = False) -> IPFSClient | None:
    """
    Initialize the global client if not present.
    Honors env:
      - IPFS_API=/ip4/127.0.0.1/tcp/5001  (for ipfshttpclient)
      - IPFS_HTTP_API=http://127.0.0.1:5001 (for HTTP fallback)
    """
    global _client
    if _client is not None and not force:
        return _client
    try:
        c = IPFSClient()
        set_client(c)
        return c
    except Exception:
        # leave None; callers can detect and fallback to local storage
        return None
