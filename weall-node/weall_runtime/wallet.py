"""
weall_runtime/wallet.py
Wallet + NFT management for Proof-of-Humanity, connected to ledger.
"""

from typing import Dict, List
from app_state import ledger  # ✅ connect to ledger

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
    ledger.ledger.record_mint_event(user_id, nft_id)  # ✅ log event
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
    ledger.ledger.record_transfer_event(old_owner, new_owner, nft_id)  # ✅ log event
    return NFT_REGISTRY[nft_id]


def burn_nft(nft_id: str) -> dict:
    """
    Burn (remove) an NFT and record in ledger.
    """
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["status"] = "burned"
    ledger.ledger.record_burn_event(owner, nft_id)  # ✅ log event
    return NFT_REGISTRY[nft_id]


def list_user_nfts(user_id: str) -> List[dict]:
    """
    Get all NFTs owned by a user.
    """
    return [n for n in NFT_REGISTRY.values() if n["owner"] == user_id]
