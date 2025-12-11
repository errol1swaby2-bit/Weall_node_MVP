"""
weall_node/api/wallet.py
------------------------
MVP wallet + faucet module for WeAll Node.

Exports:
    - wallet_router  (mounted in weall_api without prefix)
    - faucet_router  (mounted in weall_api without prefix)
"""

from typing import Dict, Any
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor

wallet_router = APIRouter()
faucet_router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wallet_state() -> Dict[str, Any]:
    """
    Ensure the wallets subtree exists and return it.

    Layout:
    executor.ledger["wallets"] = {
        "meta": {...},
        "accounts": {
            "@handle": {
                "balances": {"WEC": 0.0},
                "last_update": <unix_ts_or_none>,
                "nfts": [...],
            },
            ...
        }
    }
    """
    root = executor.ledger.setdefault("wallets", {})

    meta = root.setdefault(
        "meta",
        {
            "token_symbol": "WEC",
            "decimals": 8,
            "notes": "MVP wallets; WEC balance is mirrored from WeCoin ledger when available.",
        },
    )

    accounts = root.setdefault("accounts", {})

    return {"meta": meta, "accounts": accounts}


def _get_or_create_account(user_handle: str) -> Dict[str, Any]:
    """
    Return an account for the given @handle, creating a zeroed wallet if absent.
    """
    if not user_handle:
        raise HTTPException(status_code=400, detail="empty_user_handle")

    state = _wallet_state()
    accounts = state["accounts"]

    acct = accounts.get(user_handle)
    if acct is None:
        acct = {
            "balances": {"WEC": 0.0},
            "last_update": None,
            "nfts": [],
        }
        accounts[user_handle] = acct

    return acct


def _wecoin_balance_for(user_handle: str) -> float:
    """
    Read the canonical WEC (WeCoin) balance for this user from the WeCoin ledger,
    if the runtime is available.

    Falls back to 0.0 if WeCoin is not wired or any error occurs.
    """
    if not user_handle:
        return 0.0

    wecoin = getattr(executor, "wecoin", None)
    if wecoin is None or not hasattr(wecoin, "get_balance"):
        return 0.0

    try:
        return float(wecoin.get_balance(user_handle))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Wallet routes
# ---------------------------------------------------------------------------

@wallet_router.get("/wallets/meta")
def wallets_meta():
    """
    Basic token/wallet metadata.
    """
    state = _wallet_state()
    meta = state["meta"]
    return {
        "ok": True,
        "token_symbol": meta.get("token_symbol", "WEC"),
        "decimals": meta.get("decimals", 8),
        "notes": meta.get("notes", ""),
    }


@wallet_router.get("/wallets/{user_handle}")
def wallet_for_user(user_handle: str):
    """
    Return (and lazily create) a wallet for the given @handle.

    The WEC balance reported here is **mirrored** from the WeCoinLedger
    when available, so it reflects real protocol rewards rather than
    just the local wallet subtree.
    """
    acct = _get_or_create_account(user_handle)

    # Mirror canonical WeCoin balance into the WEC balance field if possible.
    wec_balance = _wecoin_balance_for(user_handle)
    balances = acct.setdefault("balances", {})
    balances["WEC"] = wec_balance

    return {
        "ok": True,
        "user": user_handle,
        "balances": balances,
        "nfts": acct.get("nfts", []),
        "last_update": acct.get("last_update"),
    }


class MintNftRequest(BaseModel):
    """
    Very loose NFT mint request – we only store what we get.
    """
    cid: str = Field(..., description="IPFS CID or content reference")
    title: str = Field(..., max_length=200)
    description: str = Field("", max_length=2000)
    media_type: str = Field("image", description="image|video|audio|other")


@wallet_router.post("/wallets/{user_handle}/nfts/mint")
def mint_nft(user_handle: str, body: MintNftRequest):
    """
    Append an NFT record to the user's wallet. This is an MVP stub and does
    not perform any on-chain minting – it's just structured ledger data.
    """
    acct = _get_or_create_account(user_handle)
    nfts = acct.setdefault("nfts", [])

    nft = {
        "id": f"nft_{len(nfts) + 1}",
        "cid": body.cid,
        "title": body.title,
        "description": body.description,
        "media_type": body.media_type,
        "minted_at": int(time.time()),
    }
    nfts.append(nft)
    acct["last_update"] = int(time.time())

    return {
        "ok": True,
        "user": user_handle,
        "nft": nft,
        "nft_count": len(nfts),
    }


# ---------------------------------------------------------------------------
# Faucet routes (dev-only; separate from WeCoin runtime)
# ---------------------------------------------------------------------------

class FaucetRequest(BaseModel):
    target: str = Field(..., description="@handle to credit")
    amount: float = Field(10.0, ge=0.0, le=1_000_000.0)


@faucet_router.post("/faucet/drip")
def faucet_drip(req: FaucetRequest):
    """
    Very simple dev faucet – credits `amount` WEC to the target wallet.

    NOTE: This only updates the local wallet ledger balances and does NOT
    affect the WeCoin ledger. It is intended strictly for testing / dev UIs.
    """
    acct = _get_or_create_account(req.target)
    balances = acct.setdefault("balances", {})
    current = float(balances.get("WEC", 0.0))
    new_balance = current + float(req.amount)
    balances["WEC"] = new_balance
    acct["last_update"] = int(time.time())

    return {
        "ok": True,
        "user": req.target,
        "amount": req.amount,
        "new_balance": new_balance,
    }
