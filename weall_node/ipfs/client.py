"""
IPFS Client wrapper for WeAll Node
- Provides simple connect, add, add_bytes, cat, pin, and get_info
- Manages a global client via set_client() / get_client()
"""

import ipfshttpclient

_client = None


class IPFSClient:
    def __init__(self, addr="/ip4/127.0.0.1/tcp/5001"):
        try:
            self.client = ipfshttpclient.connect(addr)
        except Exception as e:
            raise RuntimeError(f"Failed to connect to IPFS at {addr}: {e}")

    def add(self, path: str):
        """Add a file from a local path to IPFS."""
        result = self.client.add(path)
        if isinstance(result, dict):
            return result["Hash"]
        elif isinstance(result, list):
            return result[-1]["Hash"]
        return result

    def add_bytes(self, data: bytes):
        """Add raw bytes directly to IPFS."""
        return self.client.add_bytes(data)

    def cat(self, cid: str) -> bytes:
        """Retrieve content by CID."""
        return self.client.cat(cid)

    def pin(self, cid: str):
        """Pin content by CID to persist locally."""
        return self.client.pin.add(cid)

    def get_info(self, cid: str) -> dict:
        """Return metadata/stat for a CID."""
        try:
            info = self.client.files.stat(f"/ipfs/{cid}")
            return {"ok": True, "cid": cid, "info": info}
        except Exception as e:
            return {"ok": False, "cid": cid, "error": str(e)}


def set_client(client: IPFSClient | None):
    """Set the global IPFS client instance."""
    global _client
    _client = client


def get_client() -> IPFSClient | None:
    """Get the global IPFS client instance."""
    return _client
