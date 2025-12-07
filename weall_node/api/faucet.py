"""
weall_node/api/faucet.py
------------------------

Developer faucet for local/testnet usage.

- Credits test tokens into executor.ledger["balances"][user_id]
- Intended ONLY for non-production / dev environments
"""

from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from weall_node.weall_executor import executor

router = APIRouter(prefix="/dev", tags=["dev"])


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _balances_ledger() -> Dict[str, Any]:
    """
    Ensure executor.ledger["balances"] exists and is a simple
    { user_id: integer_balance } mapping.
    """
    led = executor.ledger
    bal = led.get("balances")
    if not isinstance(bal, dict):
        bal = {}
        led["balances"] = bal
    return bal


def _mark_dirty() -> None:
    """
    Mark the executor state as needing persistence, if supported.
    """
    if hasattr(executor, "mark_dirty"):
        try:
            executor.mark_dirty()
            return
        except Exception:
            pass

    if hasattr(executor, "save_state"):
        try:
            executor.save_state()
        except Exception:
            pass


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class FaucetRequest(BaseModel):
    user_id: str = Field(..., description="Logical user/account id (e.g. @errol1swaby2)")
    amount: int = Field(
        ...,
        gt=0,
        le=1_000_000,
        description="Amount of test tokens to credit (dev-only)",
    )


# ----------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------


@router.post("/faucet", name="dev_faucet")
def dev_faucet(req: FaucetRequest = Body(...)) -> Dict[str, Any]:
    """
    POST /dev/faucet

    Simple developer faucet to credit test tokens to a user.

    Example body:
      {
        "user_id": "@errol1swaby2",
        "amount": 1000
      }

    Response:
      {
        "ok": true,
        "user_id": "@errol1swaby2",
        "credited": 1000,
        "balance": 1000
      }
    """
    user_id = (req.user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    balances = _balances_ledger()
    current = int(balances.get(user_id, 0))
    new_balance = current + int(req.amount)

    balances[user_id] = new_balance
    _mark_dirty()

    return {
        "ok": True,
        "user_id": user_id,
        "credited": int(req.amount),
        "balance": new_balance,
    }

