"""
weall_runtime/wallet.py
Wallet + NFT management for Proof-of-Humanity, connected to ledger.
"""

from typing import Dict, List
from weall_node.app_state import ledger  # ✅ direct Ledger object

# In-memory storage for NFTs
NFT_REGISTRY: Dict[str, dict] = {}


def mint_nft(user_id: str, nft_id: str, metadata: str) -> dict:
    """
    Simulate minting an NFT and record it in the ledger.
    """
    nft = {
        "nft_id": nft_id,
        "owner": user_id,
        "metadata": metadata,
        "status": "minted",
    }
    NFT_REGISTRY[nft_id] = nft
    ledger.record_mint_event(user_id, nft_id)   # ✅ FIXED
    return nft


def transfer_nft(nft_id: str, new_owner: str) -> dict:
    """
    Transfer ownership of an NFT to another user and record in ledger.
    """
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    old_owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["owner"] = new_owner
    NFT_REGISTRY[nft_id]["status"] = "transferred"
    ledger.record_transfer_event(old_owner, new_owner, nft_id)   # ✅ FIXED
    return NFT_REGISTRY[nft_id]


def burn_nft(nft_id: str) -> dict:
    """
    Burn (remove) an NFT and record in ledger.
    """
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["status"] = "burned"
    ledger.record_burn_event(owner, nft_id)   # ✅ FIXED
    return NFT_REGISTRY[nft_id]


def list_user_nfts(user_id: str) -> List[dict]:
    """
    Get all NFTs owned by a user.
    """
    return [n for n in NFT_REGISTRY.values() if n["owner"] == user_id]


def has_nft(user_id: str, prefix: str, min_level: int = 1) -> bool:
    """
    Check if a user owns at least one NFT of a given type (e.g., PoH tier).
    Example: prefix="poh-tier" and min_level=1
    """
    for nft in NFT_REGISTRY.values():
        if nft["owner"] != user_id:
            continue
        if nft["nft_id"].startswith(prefix):
            try:
                tier = int(nft["nft_id"].split("-")[-1])
                if tier >= min_level and nft["status"] == "minted":
                    return True
            except Exception:
                continue
    return False
