"""
weall_node/api/wallet.py
--------------------------------------------------
Wallet API for WeCoin (WEC).

Endpoints:
- GET  /wallet/balance/{user_id}   (optional helper)
- POST /wallet/transfer            (main send endpoint)

This thin layer delegates real logic to the executor:
- executor.get_balance(user_id)
- executor.transfer_wec(from_id, to_id, amount)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..weall_executor import executor


router = APIRouter(prefix="/wallet", tags=["wallet"])


def _norm_user_id(u: str) -> str:
    """Normalize user ids (emails) in a consistent way."""
    return (u or "").strip()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TransferBody(BaseModel):
    """Request body for /wallet/transfer.

    `signature` is reserved for future use when we move
    to signed client-side transactions; for now it is
    accepted and ignored by the executor.
    """
    sender: str
    recipient: str
    amount: float
    signature: str | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _exec_balance(user_id: str) -> float:
    """
    Safe wrapper for executor.get_balance(user_id).

    Falls back to legacy ledger["balances"] or ["accounts"] if the helper
    is not present for some reason.
    """
    user_id = _norm_user_id(user_id)
    if not user_id:
        return 0.0

    # Prefer the executor helper if it exists
    try:
        bal = executor.get_balance(user_id)
        return float(bal)
    except AttributeError:
        pass  # Fall through to legacy format
    except Exception:
        return 0.0

    # Legacy: pull directly from the ledger dict
    led = getattr(executor, "ledger", {}) or {}
    balances = led.get("balances") or led.get("accounts") or {}
    try:
        bal = balances.get(user_id, 0.0)
    except AttributeError:
        bal = 0.0

    try:
        return float(bal)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/balance/{user_id}")
def wallet_balance(user_id: str):
    """
    Optional wallet-specific balance endpoint.

    Your profile page currently uses /ledger/balance/{user_id}, which is
    also fine. This exists so wallet-specific UIs have a stable home.
    """
    uid = _norm_user_id(user_id)
    if not uid:
        raise HTTPException(status_code=400, detail="user_id_required")

    bal = _exec_balance(uid)
    return {"ok": True, "user_id": uid, "balance": bal}


@router.post("/transfer")
def wallet_transfer(body: TransferBody):
    """
    Transfer WEC between two users.

    JSON body:
      {
        "sender":    "<user id / email>",
        "recipient": "<user id / email>",
        "amount":    <float>
      }

    This delegates to executor.transfer_wec(...) which performs:
    - validation
    - insufficient-funds checks
    - debit + credit
    - event logging
    """
    sender = _norm_user_id(body.sender)
    recipient = _norm_user_id(body.recipient)

    if not sender or not recipient:
        raise HTTPException(
            status_code=400,
            detail="sender_and_recipient_required",
        )

    try:
        amount = float(body.amount)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_amount")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount_must_be_positive")

    if sender == recipient:
        raise HTTPException(status_code=400, detail="cannot_send_to_self")

    # Delegate to the executor helper if available
    try:
        result = executor.transfer_wec(sender, recipient, amount)
    except AttributeError:
        # Older executor without helper: use a simple fallback implementation
        sender_balance = _exec_balance(sender)
        if sender_balance < amount:
            raise HTTPException(status_code=400, detail="insufficient_funds")

        # Basic manual debit / credit path
        led = getattr(executor, "ledger", None)
        if led is None:
            led = {}
            executor.ledger = led
        balances = led.setdefault("balances", {})

        balances[sender] = float(sender_balance - amount)
        balances[recipient] = float(_exec_balance(recipient) + amount)
        try:
            executor.save_state()
        except Exception:
            pass

        result = {
            "ok": True,
            "from": sender,
            "to": recipient,
            "amount": float(amount),
            "from_balance": float(balances[sender]),
            "to_balance": float(balances[recipient]),
        }

    # Normalize error handling from executor.transfer_wec
    if not result.get("ok", False):
        err = result.get("error", "transfer_failed")
        if err == "insufficient_funds":
            raise HTTPException(status_code=400, detail=err)
        raise HTTPException(status_code=500, detail=err)

    return result
