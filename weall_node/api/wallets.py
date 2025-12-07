"""
weall_node/api/wallets.py
-------------------------
MVP wallets module for WeAll Node.

- Stores very simple wallet state in executor.ledger["wallets"]
- Does NOT yet wire on-chain balances; this is a view + stub.
"""

from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from ..weall_executor import executor

router = APIRouter()


def _ensure_wallet_state() -> Dict[str, Any]:
    """
    Ensure the wallets ledger subtree exists and return it.

    Layout:
    executor.ledger["wallets"] = {
        "meta": {...},
        "accounts": {
            "@handle": {
                "balances": {"WEC": 0.0},
                "last_update": <unix_ts_or_none>,
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
            "notes": "MVP wallet view; balances not yet wired to chain rewards.",
        },
    )

    accounts = root.setdefault("accounts", {})

    # Return the entire subtree so callers can use meta/accounts.
    return {"meta": meta, "accounts": accounts}


@router.get("/meta")
def get_wallet_meta():
    """
    Basic token + wallet meta.
    """
    state = _ensure_wallet_state()
    meta = state["meta"]
    return {
        "ok": True,
        "token_symbol": meta.get("token_symbol", "WEC"),
        "decimals": meta.get("decimals", 8),
        "notes": meta.get("notes", ""),
    }


@router.get("/{user_handle}")
def get_wallet(user_handle: str):
    """
    Return (and lazily create) a simple wallet for the given @handle.
    """
    if not user_handle:
        raise HTTPException(status_code=400, detail="empty_user_handle")

    state = _ensure_wallet_state()
    accounts = state["accounts"]

    # Ensure the handle is stored exactly as called (e.g. "@errol1swaby2").
    acct = accounts.get(user_handle)
    if acct is None:
        acct = {
            "balances": {"WEC": 0.0},
            "last_update": None,
        }
        accounts[user_handle] = acct
        # NOTE: we intentionally DO NOT call executor.save()/commit() here
        # because the current WeAllExecutor wrapper does not expose that.
        # Persistence is handled elsewhere in the stack.

    return {
        "ok": True,
        "user": user_handle,
        "balances": acct.get("balances", {}),
        "last_update": acct.get("last_update"),
    }
