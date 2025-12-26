from __future__ import annotations

"""
Audit proofs + hashing helpers.

Provides:
- canonical_json_bytes(obj) -> stable serialization for hashing
- sha256_hex(bytes)
- receipt_hash(receipt_dict)
- merkle_root(list_of_hex_strings)

Goal:
- Make receipts and blocks independently verifiable with stable hashes.
"""

import hashlib
import json
from typing import Any, Dict, List


def canonical_json_bytes(obj: Any) -> bytes:
    # Canonical JSON for hashing: stable sort + compact separators
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def receipt_hash(receipt: Dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(receipt))


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(a + b).digest()


def merkle_root(hex_leaves: List[str]) -> str:
    """
    Merkle root over leaf strings that are hex digests/ids.
    - Leaves are hashed as SHA256(leaf_bytes) to normalize.
    - Tree is built by hashing pairs; odd leaf is duplicated.
    - Returns hex digest.
    """
    leaves = [x.strip().lower() for x in (hex_leaves or []) if isinstance(x, str) and x.strip()]
    if not leaves:
        return sha256_hex(b"")

    level = [hashlib.sha256(bytes.fromhex(x) if _is_hex(x) else x.encode("utf-8")).digest() for x in leaves]

    while len(level) > 1:
        nxt = []
        i = 0
        while i < len(level):
            left = level[i]
            right = level[i + 1] if (i + 1) < len(level) else left
            nxt.append(_hash_pair(left, right))
            i += 2
        level = nxt

    return level[0].hex()


def _is_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return True
    except Exception:
        return False
