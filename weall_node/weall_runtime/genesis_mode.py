"""
Genesis Mode bootstrap utilities.

Goal:
- Allow first-time operator bootstrap without manual PoH/NFT verification.
- Only works in non-production and only on an empty chain.

Hard guards:
- WEALL_GENESIS=1 must be set
- WEALL_ENV must NOT be 'production'
- chain height must be 0 (no blocks)
- only first user can be bootstrapped
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple


DEFAULT_GENESIS_NFTS: List[Dict[str, Any]] = [
    {"id": "POH_TIER1", "name": "WeAll PoH Tier 1", "tier": 1},
    {"id": "POH_TIER2", "name": "WeAll PoH Tier 2", "tier": 2},
    {"id": "POH_TIER3", "name": "WeAll PoH Tier 3", "tier": 3},
]


def genesis_enabled() -> bool:
    env = (os.getenv("WEALL_ENV") or "").strip().lower()
    if env == "production":
        return False
    return (os.getenv("WEALL_GENESIS") or "").strip() in ("1", "true", "yes", "on")


def _chain_is_empty(ledger: Dict[str, Any]) -> bool:
    chain = ledger.get("chain") or ledger.get("chain", [])
    if isinstance(chain, dict):
        # some ledgers store chain under ledger["chain"]["blocks"]
        blocks = chain.get("blocks") or []
        return len(blocks) == 0
    if isinstance(chain, list):
        return len(chain) == 0
    return True


def _count_known_users(ledger: Dict[str, Any]) -> int:
    # Try to count auth users if present in ledger
    auth = ledger.get("auth") or {}
    users = auth.get("users") or {}
    if isinstance(users, dict):
        return len(users)

    # Fallback: count wallet accounts
    wallets = ledger.get("wallets") or {}
    accounts = wallets.get("accounts") or {}
    if isinstance(accounts, dict):
        return len(accounts)

    return 0


def _ensure_wallet_account(ledger: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    wallets = ledger.setdefault("wallets", {})
    wallets.setdefault("meta", {"token_symbol": "WEC", "decimals": 8})
    accounts = wallets.setdefault("accounts", {})
    acct = accounts.get(user_id)
    if acct is None:
        acct = {"balances": {"WEC": 0.0}, "last_update": None, "nfts": []}
        accounts[user_id] = acct
    return acct


def _ensure_poh_record(ledger: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    poh = ledger.setdefault("poh", {})
    records = poh.setdefault("records", {})
    rec = records.get(user_id)
    if rec is None:
        rec = {
            "user_id": user_id,
            "tier": 0,
            "tier_label": "observer",
            "history": [],
            "evidence_hashes": [],
        }
        records[user_id] = rec
    return rec


def try_bootstrap_first_user(ledger: Dict[str, Any], user_id: str) -> Tuple[bool, str]:
    """
    Returns (bootstrapped, reason).
    """
    if not genesis_enabled():
        return False, "genesis_disabled"

    if not _chain_is_empty(ledger):
        return False, "chain_not_empty"

    if _count_known_users(ledger) > 0:
        # One-time only: first user wins
        return False, "not_first_user"

    now = int(time.time())

    # PoH: elevate to Tier 3
    rec = _ensure_poh_record(ledger, user_id)
    rec["tier"] = 3
    rec["tier_label"] = "tier3"
    rec.setdefault("history", []).append({"ts": now, "event": "genesis_bootstrap_tier3"})

    # Wallet: mint NFTs
    acct = _ensure_wallet_account(ledger, user_id)
    existing = {str(n.get("id")) for n in (acct.get("nfts") or []) if isinstance(n, dict)}
    for nft in DEFAULT_GENESIS_NFTS:
        if nft["id"] not in existing:
            acct["nfts"].append(
                {
                    "id": nft["id"],
                    "name": nft["name"],
                    "tier": nft["tier"],
                    "minted_at": now,
                    "source": "genesis_mode",
                }
            )

    acct["last_update"] = now

    return True, "bootstrapped"
