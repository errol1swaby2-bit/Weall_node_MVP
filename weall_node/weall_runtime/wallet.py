"""
weall_runtime/wallet.py
--------------------------------------------------
Wallet + NFT management for Proof-of-Humanity,
connected to ledger. Provides mint/transfer/burn
helpers and an adaptive has_nft() for access checks.
"""

import json, os
from typing import Dict, List
from weall_node.app_state import ledger  # ✅ direct Ledger object

# ---------------------------------------------------------------
# In-memory NFT registry
# ---------------------------------------------------------------
NFT_REGISTRY: Dict[str, dict] = {}


# ---------------------------------------------------------------
# NFT mint / transfer / burn
# ---------------------------------------------------------------
def mint_nft(user_id: str, nft_id: str, metadata: str) -> dict:
    """Simulate minting an NFT and record it in the ledger."""
    nft = {
        "nft_id": nft_id,
        "owner": user_id,
        "metadata": metadata,
        "status": "minted",
    }
    NFT_REGISTRY[nft_id] = nft
    ledger.record_mint_event(user_id, nft_id)
    return nft


def transfer_nft(nft_id: str, new_owner: str) -> dict:
    """Transfer ownership of an NFT to another user and record in ledger."""
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    old_owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["owner"] = new_owner
    NFT_REGISTRY[nft_id]["status"] = "transferred"
    ledger.record_transfer_event(old_owner, new_owner, nft_id)
    return NFT_REGISTRY[nft_id]


def burn_nft(nft_id: str) -> dict:
    """Burn (remove) an NFT and record in ledger."""
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["status"] = "burned"
    ledger.record_burn_event(owner, nft_id)
    return NFT_REGISTRY[nft_id]


# ---------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------
def list_user_nfts(user_id: str) -> List[dict]:
    """Return all NFTs owned by the given user."""
    return [n for n in NFT_REGISTRY.values() if n["owner"] == user_id]


# ---------------------------------------------------------------
# NFT ownership check (multi-layer)
# ---------------------------------------------------------------
def has_nft(user_id: str, prefix: str = "POH", min_level: int = 1) -> bool:
    """
    Return True if the user owns an NFT of the given prefix and at least `min_level`.
    Searches memory (NFT_REGISTRY), ledger events, then on-disk chain.json.
    """

    # --- 0. Ensure registry exists safely ---
    global NFT_REGISTRY
    try:
        NFT_REGISTRY
    except NameError:
        NFT_REGISTRY = {}

    # --- 1. In-memory NFTs (fast path) ---
    for nft in NFT_REGISTRY.values():
        if nft.get("owner") != user_id:
            continue
        nft_id = nft.get("nft_id", "")
        if prefix in nft_id:
            try:
                # handle IDs like POH_T1::alice::timestamp
                if "_T" in nft_id:
                    tier = int(nft_id.split("_T")[1].split("::")[0])
                elif "-" in nft_id:
                    tier = int(nft_id.split("-")[-1])
                else:
                    tier = 1
                if tier >= min_level and nft.get("status") == "minted":
                    return True
            except Exception:
                continue

    # --- 2. Ledger mint events ---
    try:
        if hasattr(ledger, "mint_events"):
            for evt in ledger.mint_events:
                nft_id = evt.get("nft_id", "")
                owner = evt.get("user_id") or evt.get("owner")
                if owner != user_id:
                    continue
                if prefix in nft_id:
                    try:
                        tier = int(nft_id.split("_T")[1].split("::")[0])
                        if tier >= min_level:
                            return True
                    except Exception:
                        continue
    except Exception:
        pass

    # --- 3. Fallback to on-disk chain.json ---
    try:
        if os.path.exists("chain.json"):
            with open("chain.json") as f:
                chain = json.load(f)
            for block in chain:
                for tx in block.get("txs", []):
                    ttype = tx.get("type", "")
                    u = tx.get("user")
                    if not u or u != user_id:
                        continue
                    if ttype.startswith("POH_TIER"):
                        try:
                            tier = int(ttype.replace("POH_TIER", "").split("_")[0])
                            if tier >= min_level:
                                return True
                        except Exception:
                            continue
    except Exception:
        pass

    return False
