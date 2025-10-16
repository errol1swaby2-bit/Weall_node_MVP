#!/usr/bin/env python3
"""
weall_node.app_state.chain
---------------------------
Implements the in-memory and persisted blockchain state for the WeAll Protocol.

Features:
- Transaction mempool
- Deterministic block finalization
- Persistent block chain
- Integration point for Tier-3 validator verification
"""

import os
import json
import time
import hashlib
from typing import List, Dict, Any


class ChainState:
    def __init__(self):
        self.blocks: List[dict] = []
        self.mempool: List[dict] = []
        self.repo_path = None

    # ---------------------------------------------------------
    # Utility
    # ---------------------------------------------------------
    @staticmethod
    def _hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()

    def _latest_hash(self) -> str:
        return self.blocks[-1]["hash"] if self.blocks else "genesis"

    # ---------------------------------------------------------
    # Mempool
    # ---------------------------------------------------------
    def record_to_mempool(self, tx: Dict[str, Any]) -> None:
        """Append a transaction to the mempool."""
        self.mempool.append(
            {"tx": tx, "ts": int(time.time()), "hash": self._hash(json.dumps(tx, sort_keys=True))}
        )

    def get_mempool(self) -> List[dict]:
        return list(self.mempool)

    def clear_mempool(self):
        self.mempool.clear()

    # ---------------------------------------------------------
    # Blocks
    # ---------------------------------------------------------
    def finalize_block(self, validator_id: str) -> dict:
        """Creates a block from current mempool and finalizes it with validator ID."""
        ts = int(time.time())
        prev = self._latest_hash()
        block = {
            "ts": ts,
            "prev": prev,
            "validator": validator_id,
            "txs": [m["tx"] for m in self.mempool],
        }
        block["hash"] = self._hash(json.dumps(block, sort_keys=True))
        self.blocks.append(block)
        self.clear_mempool()
        return block

    def all_blocks(self) -> List[dict]:
        return list(self.blocks)

    def latest(self) -> dict:
        return self.blocks[-1] if self.blocks else {}

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------
    def save(self, path: str):
        """Persist blocks and mempool to disk."""
        try:
            with open(path, "w") as f:
                json.dump({"blocks": self.blocks, "mempool": self.mempool}, f, indent=2)
        except Exception as e:
            print(f"[chain.save] {e}")

    def load(self, path: str):
        """Load blocks and mempool from disk, if available."""
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.blocks = data.get("blocks", [])
            self.mempool = data.get("mempool", [])
        except Exception as e:
            print(f"[chain.load] {e}")

    # ---------------------------------------------------------
    # Reset
    # ---------------------------------------------------------
    def reset(self):
        """Clear chain state (for testing or re-initialization)."""
        self.blocks.clear()
        self.mempool.clear()
