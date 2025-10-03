"""
weall_runtime.storage

IPFS storage client with in-memory fallback.
- If ipfshttpclient is available and daemon is running, uses it.
- Otherwise, falls back to a local memory dict keyed by fake CIDs.
"""

import hashlib
from typing import Optional, Dict


class NodeStorage:
    def __init__(self, addr: str = "/ip4/127.0.0.1/tcp/5001/http"):
        self._ipfs = None
        self._memory: Dict[str, bytes] = {}
        try:
            import ipfshttpclient
            self._ipfs = ipfshttpclient.connect(addr)
        except Exception:
            self._ipfs = None  # fallback to memory only

    # -------------------
    # Store content
    # -------------------
    def add_bytes(self, data: bytes) -> str:
        if self._ipfs:
            try:
                return self._ipfs.add_bytes(data)
            except Exception:
                pass  # fallback on failure
        # Fallback: memory
        cid = f"cid-{hashlib.sha256(data).hexdigest()[:16]}"
        self._memory[cid] = data
        return cid

    def add_text(self, text: str) -> str:
        return self.add_bytes(text.encode())

    # -------------------
    # Retrieve content
    # -------------------
    def get(self, cid: str) -> Optional[bytes]:
        if self._ipfs:
            try:
                return self._ipfs.cat(cid)
            except Exception:
                pass
        return self._memory.get(cid)

    # -------------------
    # Pinning (noop in memory mode)
    # -------------------
    def pin_add(self, cid: str) -> None:
        if self._ipfs:
            try:
                self._ipfs.pin.add(cid)
            except Exception:
                pass  # ignore in fallback mode

    # -------------------
    # Cleanup
    # -------------------
    def close(self):
        if self._ipfs:
            try:
                self._ipfs.close()
            except Exception:
                pass


# Global singleton
_client: Optional[NodeStorage] = None


def set_client(c: Optional[NodeStorage]):
    global _client
    _client = c


def get_client() -> Optional[NodeStorage]:
    return _client
