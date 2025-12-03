"""
weall_node/weall_runtime/wallet.py
--------------------------------------------------
Wallet + NFT management for Proof-of-Humanity.
Provides mint/transfer/burn helpers and a has_nft()
utility used by the validator and PoH modules.
"""

import json, os
from typing import Dict, List, Any

# Attempt to load the unified ledger object from the executor runtime
try:
    from weall_node.weall_executor import executor

    ledger = executor.ledger
except Exception:
    # fallback: minimal in-memory ledger for local dev
    ledger = {}

# ---------------------------------------------------------------
# In-memory NFT registry
# ---------------------------------------------------------------
NFT_REGISTRY: Dict[str, dict] = {}


# ---------------------------------------------------------------
# NFT mint / transfer / burn
# ---------------------------------------------------------------
def mint_nft(user_id: str, nft_id: str, metadata: Any) -> dict:
    """Simulate minting an NFT and record it in the ledger."""
    nft = {
        "nft_id": nft_id,
        "owner": user_id,
        "metadata": metadata,
        "status": "minted",
    }
    NFT_REGISTRY[nft_id] = nft
    # also record in ledger if supported
    if hasattr(ledger, "record_nft"):
        ledger.record_nft(user_id, nft_id, metadata)
    return nft


def transfer_nft(nft_id: str, new_owner: str) -> bool:
    """Transfer NFT ownership."""
    if nft_id not in NFT_REGISTRY:
        return False
    NFT_REGISTRY[nft_id]["owner"] = new_owner
    NFT_REGISTRY[nft_id]["status"] = "transferred"
    return True


def burn_nft(nft_id: str) -> bool:
    """Burn an NFT."""
    if nft_id not in NFT_REGISTRY:
        return False
    NFT_REGISTRY[nft_id]["status"] = "burned"
    return True


# ---------------------------------------------------------------
# has_nft() — required by validators.py
# ---------------------------------------------------------------
def has_nft(user_id: str, nft_type: str = None) -> bool:
    """
    Check if a user holds an active NFT, optionally of a given type.
    Validators and PoH modules use this to check tier access.
    """
    for nft in NFT_REGISTRY.values():
        if nft["owner"] == user_id and nft.get("status") == "minted":
            if nft_type is None or nft.get("metadata", {}).get("type") == nft_type:
                return True
    return False


# ---------------------------------------------------------------
# Utility: List all NFTs for a user
# ---------------------------------------------------------------
def list_user_nfts(user_id: str) -> List[dict]:
    return [n for n in NFT_REGISTRY.values() if n["owner"] == user_id]


# ---------------------------------------------------------------
# Proof-of-Humanity NFT Integration
# ---------------------------------------------------------------

# Map tier levels to canonical NFT types
TIER_BADGE_MAP = {
    1: "poh_tier1_badge",
    2: "poh_tier2_badge",
    3: "poh_tier3_badge",
}


def ensure_poh_badge(user_id: str, tier: int) -> dict:
    """
    Ensure a user owns an NFT badge matching their PoH tier.
    Called automatically when advancing through verification.
    """
    nft_type = TIER_BADGE_MAP.get(tier)
    if not nft_type:
        raise ValueError(f"Invalid PoH tier: {tier}")

    # Return existing badge if already minted
    for nft in NFT_REGISTRY.values():
        if (
            nft["owner"] == user_id
            and nft.get("metadata", {}).get("type") == nft_type
            and nft.get("status") == "minted"
        ):
            return nft

    # Otherwise, mint a new badge NFT
    metadata = {
        "type": nft_type,
        "tier": tier,
        "title": f"Proof of Humanity Tier {tier}",
    }
    nft_id = f"{user_id}_{nft_type}"
    return mint_nft(user_id, nft_id, metadata)


# Extend has_nft() to include PoH badge detection
def has_nft(user_id: str, nft_type: str = None) -> bool:
    """
    Check if user holds an active NFT.
    If nft_type is 'poh_verified', any tier badge qualifies.
    """
    for nft in NFT_REGISTRY.values():
        if nft["owner"] == user_id and nft.get("status") == "minted":
            nft_t = nft.get("metadata", {}).get("type")
            if nft_type is None or nft_t == nft_type:
                return True
            if nft_type == "poh_verified" and nft_t in TIER_BADGE_MAP.values():
                return True
    return False
