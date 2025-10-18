"""
weall_runtime/wallet.py
--------------------------------------------------
Wallet + NFT management for Proof-of-Humanity,
connected to the node's ledger. Provides mint /
transfer / burn helpers and ownership lookup.
"""

import time, os, json
from typing import Dict, List, Optional

# ---------------------------------------------------------------
# WalletRuntime: manages user balances, NFT registry, and ledger events
# ---------------------------------------------------------------
class WalletRuntime:
    def __init__(self, ledger=None):
        """
        Initialize the wallet runtime.
        :param ledger: optional LedgerRuntime instance (attached by executor)
        """
        self.ledger = ledger
        self.balances: Dict[str, float] = {}
        self.nfts: Dict[str, dict] = {}

    # -----------------------------------------------------------
    # User funds
    # -----------------------------------------------------------
    def create_account(self, uid: str):
        """Create a wallet entry for a user."""
        self.balances.setdefault(uid, 0.0)

    def balance(self, uid: str) -> float:
        """Return a user's balance."""
        return self.balances.get(uid, 0.0)

    def transfer(self, sender: str, recipient: str, amount: float) -> dict:
        """Transfer funds between users."""
        amt = float(amount)
        if self.balances.get(sender, 0.0) < amt:
            return {"ok": False, "error": "insufficient_funds"}
        self.balances[sender] -= amt
        self.balances[recipient] = self.balances.get(recipient, 0.0) + amt
        if self.ledger and hasattr(self.ledger, "record_transfer_event"):
            self.ledger.record_transfer_event(sender, recipient, f"funds:{amt}")
        return {"ok": True, "sender_balance": self.balances[sender],
                "recipient_balance": self.balances[recipient]}

    # -----------------------------------------------------------
    # NFT mint / transfer / burn
    # -----------------------------------------------------------
    def mint_nft(self, user_id: str, nft_id: str, metadata: str) -> dict:
        """Mint an NFT and record it in the ledger if available."""
        nft = {
            "nft_id": nft_id,
            "owner": user_id,
            "metadata": metadata,
            "status": "minted",
            "ts": int(time.time()),
        }
        self.nfts[nft_id] = nft
        if self.ledger and hasattr(self.ledger, "record_mint_event"):
            self.ledger.record_mint_event(user_id, nft_id)
        return {"ok": True, "nft": nft}

    def transfer_nft(self, nft_id: str, new_owner: str) -> dict:
        """Transfer ownership of an NFT to another user."""
        if nft_id not in self.nfts:
            return {"ok": False, "error": f"NFT {nft_id} not found"}
        old_owner = self.nfts[nft_id]["owner"]
        self.nfts[nft_id]["owner"] = new_owner
        self.nfts[nft_id]["status"] = "transferred"
        if self.ledger and hasattr(self.ledger, "record_transfer_event"):
            self.ledger.record_transfer_event(old_owner, new_owner, nft_id)
        return {"ok": True, "nft": self.nfts[nft_id]}

    def burn_nft(self, nft_id: str) -> dict:
        """Burn (remove) an NFT and record in ledger."""
        if nft_id not in self.nfts:
            return {"ok": False, "error": f"NFT {nft_id} not found"}
        owner = self.nfts[nft_id]["owner"]
        self.nfts[nft_id]["status"] = "burned"
        if self.ledger and hasattr(self.ledger, "record_burn_event"):
            self.ledger.record_burn_event(owner, nft_id)
        return {"ok": True, "nft": self.nfts[nft_id]}

    # -----------------------------------------------------------
    # NFT queries
    # -----------------------------------------------------------
    def list_user_nfts(self, user_id: str) -> List[dict]:
        """Return all NFTs owned by the given user."""
        return [n for n in self.nfts.values() if n["owner"] == user_id]

    def has_nft(self, user_id: str, prefix: str = "POH", min_level: int = 1) -> bool:
        """
        Return True if the user owns an NFT of the given prefix and tier ≥ min_level.
        Checks in-memory registry, then optional chain.json file.
        """
        # 1. In-memory check
        for nft in self.nfts.values():
            if nft.get("owner") != user_id:
                continue
            nid = nft.get("nft_id", "")
            if prefix in nid and nft.get("status") == "minted":
                try:
                    tier = int(nid.split("_T")[1].split("::")[0]) if "_T" in nid else 1
                except Exception:
                    tier = 1
                if tier >= min_level:
                    return True

        # 2. Optional chain.json fallback
        try:
            if os.path.exists("chain.json"):
                with open("chain.json") as f:
                    chain = json.load(f)
                for block in chain:
                    for tx in block.get("txs", []):
                        ttype = tx.get("type", "")
                        u = tx.get("user")
                        if u != user_id:
                            continue
                        if prefix in ttype:
                            try:
                                tier = int(ttype.split("TIER")[1].split("_")[0])
                                if tier >= min_level:
                                    return True
                            except Exception:
                                continue
        except Exception:
            pass
        return False
