#!/usr/bin/env python3
import time, json, hashlib, os
from typing import List, Dict

CHAIN_FILE = "chain.json"


class ChainState:
    def __init__(self):
        self.blocks: List[dict] = []
        self.mempool: List[dict] = []  # mempool for pending txs
        self.load()

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()

    def _merkle_root(self, txs: List[dict]) -> str:
        """Compute Merkle root of transactions."""
        if not txs:
            return self._hash("empty")

        hashes = [self._hash(json.dumps(tx, sort_keys=True)) for tx in txs]
        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])  # duplicate last if odd
            hashes = [
                self._hash(hashes[i] + hashes[i + 1])
                for i in range(0, len(hashes), 2)
            ]
        return hashes[0]

    # ---------------------------------------------------------------
    # Basic block adder (used by PoH and system-level txs)
    # ---------------------------------------------------------------
    def add_block(self, txs: List[dict]) -> dict:
        """Lightweight block adder for PoH verifications and internal events."""
        ts = int(time.time())
        prev_hash = self.blocks[-1]["hash"] if self.blocks else "genesis"

        block = {
            "ts": ts,
            "txs": txs,
            "prev": prev_hash,
            "validator": "system",
            "merkle_root": self._merkle_root(txs),
            "sig": "system-auto",
        }

        raw = json.dumps(block, sort_keys=True)
        block["hash"] = self._hash(raw)
        self.blocks.append(block)
        self.persist()
        return block

    # ---------------------------------------------------------------
    # Mempool + Block Production (Validator-signed)
    # ---------------------------------------------------------------
    def add_tx(self, tx: dict):
        """Add a transaction to the mempool."""
        self.mempool.append(tx)

    def produce_block(self, validator_id: str, priv_key, pub_key, crypto_utils) -> dict:
        """Create a signed block from mempool transactions."""
        ts = int(time.time())
        prev_hash = self.blocks[-1]["hash"] if self.blocks else "genesis"
        txs = self.mempool[:]
        root = self._merkle_root(txs)

        block = {
            "ts": ts,
            "txs": txs,
            "prev": prev_hash,
            "validator": validator_id,
            "merkle_root": root,
        }

        raw = json.dumps(block, sort_keys=True).encode()
        sig = crypto_utils.sign(priv_key, raw)
        block["sig"] = sig
        block["hash"] = self._hash((raw + sig.encode()).decode("latin1"))

        self.blocks.append(block)
        self.persist()
        self.mempool.clear()
        return block

    # ---------------------------------------------------------------
    # Verification
    # ---------------------------------------------------------------
    def verify_block(self, block: dict, executor, crypto_utils) -> dict:
        """Verify a received block from a peer."""
        required_fields = {
            "ts", "txs", "prev", "validator", "sig", "hash", "merkle_root"
        }
        if not all(k in block for k in required_fields):
            return {"ok": False, "error": "missing_fields"}

        # 1. Check prev-hash
        latest = self.latest()
        if latest and block["prev"] != latest["hash"]:
            return {"ok": False, "error": "invalid_prev_hash"}

        # 2. Recompute merkle root
        if block["merkle_root"] != self._merkle_root(block["txs"]):
            return {"ok": False, "error": "merkle_root_mismatch"}

        # 3. Recompute hash
        raw_block = {k: v for k, v in block.items() if k != "hash"}
        raw_json = json.dumps(raw_block, sort_keys=True).encode()
        recomputed_hash = self._hash((raw_json + block["sig"].encode()).decode("latin1"))
        if block["hash"] != recomputed_hash:
            return {"ok": False, "error": "hash_mismatch"}

        # 4. Verify signature
        validator_id = block["validator"]
        user = executor.state["users"].get(validator_id)
        if not user:
            return {"ok": False, "error": "unknown_validator"}

        pub = user["public_key"]
        if not crypto_utils.verify(pub, raw_json, block["sig"]):
            return {"ok": False, "error": "invalid_signature"}

        # 5. Check validator is Tier-3
        if user.get("poh_level", 0) < 3:
            return {"ok": False, "error": "validator_not_tier3"}

        # All good → append
        self.blocks.append(block)
        self.persist()
        return {"ok": True, "hash": block["hash"]}

    # ---------------------------------------------------------------
    # Block accessors and persistence
    # ---------------------------------------------------------------
    def all_blocks(self) -> List[dict]:
        return self.blocks

    def latest(self) -> dict:
        return self.blocks[-1] if self.blocks else {}

    def persist(self):
        """Persist the full chain to disk."""
        with open(CHAIN_FILE, "w") as f:
            json.dump(self.blocks, f, indent=2)

    def load(self):
        """Load chain state from disk."""
        if os.path.exists(CHAIN_FILE):
            with open(CHAIN_FILE) as f:
                self.blocks = json.load(f)


# ---------------------------------------------------------------
# Global singleton for app-wide access
# ---------------------------------------------------------------
chain_instance = ChainState()
