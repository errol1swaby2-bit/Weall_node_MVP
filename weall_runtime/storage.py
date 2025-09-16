# weall_runtime/storage.py
"""
Storage abstraction for WeAll that supports:
- IPFS (if ipfshttpclient is available)
- Local fallback storage (useful for testing / CI / offline dev)

API:
- IPFSClient.connect()  # returns client
- client.add_str(content) -> cid
- client.get_str(cid) -> content
- client.pin(cid) -> None (no-op fallback)
"""

import os
import json
import hashlib
from typing import Optional

# Try to import ipfshttpclient; if missing, we'll use local store
try:
    import ipfshttpclient  # type: ignore
    _HAS_IPFS = True
except Exception:
    ipfshttpclient = None
    _HAS_IPFS = False

DEFAULT_LOCAL_DIR = os.path.join(os.getcwd(), ".weall_ipfs_store")


class IPFSClient:
    def __init__(self, local_dir: Optional[str] = None):
        self.local_dir = local_dir or DEFAULT_LOCAL_DIR
        os.makedirs(self.local_dir, exist_ok=True)
        self._client = None
        if _HAS_IPFS:
            try:
                self._client = ipfshttpclient.connect()
            except Exception:
                self._client = None

    def is_ipfs_available(self) -> bool:
        return self._client is not None

    # --- helpers for local fallback ---
    def _local_cid_for(self, content: str) -> str:
        # deterministic cid-like id using sha256 hex
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"local-{h}"

    def _local_path(self, cid: str) -> str:
        return os.path.join(self.local_dir, cid + ".json")

    # --- public API ---
    def add_str(self, content: str) -> str:
        """
        Add content to IPFS if available, otherwise to local store.
        Returns a cid (string).
        """
        if self._client:
            try:
                # ipfshttpclient has add_str in older versions; fallback to add_bytes
                try:
                    cid = self._client.add_str(content)
                    return str(cid)
                except Exception:
                    res = self._client.add_bytes(content.encode("utf-8"))
                    # add_bytes returns a multihash; return str
                    return str(res)
            except Exception:
                # fallthrough to local
                pass

        # local fallback
        cid = self._local_cid_for(content)
        path = self._local_path(cid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"content": content}, f)
        return cid

    def get_str(self, cid: str) -> Optional[str]:
        """
        Retrieve content by cid. Returns None if not found.
        """
        if self._client:
            try:
                # try cat
                try:
                    raw = self._client.cat(cid)
                    if isinstance(raw, bytes):
                        return raw.decode("utf-8")
                    return str(raw)
                except Exception:
                    # try get and read file
                    res = self._client.get(cid)
                    # client.get writes to disk: try to read from returned path if present
                    if hasattr(res, "get") or isinstance(res, (list, dict)):
                        # not reliable across ipfshttpclient versions; fallback to local
                        pass
            except Exception:
                pass

        # local fallback
        path = self._local_path(cid)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return obj.get("content")
        return None

    def pin(self, cid: str) -> None:
        """
        Attempt to pin CID (no-op in local fallback).
        """
        if self._client:
            try:
                self._client.pin.add(cid)
            except Exception:
                pass
        return None
