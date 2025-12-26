"""
weall_node/api/wallet.py
------------------------
Wallet + NFT + compatibility routes for WeAll Node.
"""

from typing import Dict, Any
import time

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..security.current_user import current_user_id_from_cookie_optional

wallet_router = APIRouter(tags=["wallet"])
faucet_router = APIRouter(tags=["wallet"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _wallet_state() -> Dict[str, Any]:
    root = executor.ledger.setdefault("wallets", {})
    root.setdefault("meta", {
        "token_symbol": "WEC",
        "decimals": 8,
        "notes": "MVP wallet ledger",
    })
    root.setdefault("accounts", {})
    return root


def _get_or_create_account(user_handle: str) -> Dict[str, Any]:
    if not user_handle:
        raise HTTPException(status_code=400, detail="missing_user")
    state = _wallet_state()
    acct = state["accounts"].get(user_handle)
    if acct is None:
        acct = {
            "balances": {"WEC": 0.0},
            "last_update": None,
            "nfts": [],
        }
        state["accounts"][user_handle] = acct
    return acct


# ---------------------------------------------------------------------------
# COMPATIBILITY ROUTES (WEB UI)
# ---------------------------------------------------------------------------

@wallet_router.get("/wallet/me")
def wallet_me(user_id: str = Depends(current_user_id_from_cookie_optional)):
    if not user_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    acct = _get_or_create_account(user_id)
    return {
        "ok": True,
        "user": user_id,
        "balances": acct["balances"],
        "nfts": acct["nfts"],
        "last_update": acct["last_update"],
    }


class WalletTransferRequest(BaseModel):
    to: str
    amount: float = Field(..., gt=0)


@wallet_router.post("/wallet/transfer")
def wallet_transfer(
    body: WalletTransferRequest,
    user_id: str = Depends(current_user_id_from_cookie_optional),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="not_authenticated")

    from_acct = _get_or_create_account(user_id)
    to_acct = _get_or_create_account(body.to)

    bal = float(from_acct["balances"].get("WEC", 0.0))
    if bal < body.amount:
        raise HTTPException(status_code=400, detail="insufficient_balance")

    from_acct["balances"]["WEC"] = bal - body.amount
    to_acct["balances"]["WEC"] += body.amount

    now = int(time.time())
    from_acct["last_update"] = now
    to_acct["last_update"] = now

    return {"ok": True}


@wallet_router.get("/wallet/nfts")
def wallet_nfts(user_id: str = Depends(current_user_id_from_cookie_optional)):
    if not user_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    acct = _get_or_create_account(user_id)
    return {"ok": True, "nfts": acct["nfts"]}


# ---------------------------------------------------------------------------
# EXISTING /wallets/* ROUTES PRESERVED
# ---------------------------------------------------------------------------

@wallet_router.get("/wallets/{user_handle}")
def wallet_for_user(user_handle: str):
    acct = _get_or_create_account(user_handle)
    return {
        "ok": True,
        "user": user_handle,
        "balances": acct["balances"],
        "nfts": acct["nfts"],
        "last_update": acct["last_update"],
    }
