#!/usr/bin/env python3
"""
Treasury API
-------------------------------------------------
Handles community treasury accounting, deposits,
withdrawals, and DAO-based fund allocations.

Integrates directly with the shared ledger runtime.
"""

from fastapi import APIRouter, HTTPException, Query
from weall_node.app_state import ledger
from weall_node.weall_runtime.wallet import has_nft

router = APIRouter(prefix="/treasury", tags=["treasury"])

# -------------------------------------------------
# In-memory bootstrap treasury (for early testnet)
# -------------------------------------------------
treasury_state = {
    "funds": 0.0,
    "allocations": {},  # proposal_id -> {"amount": x, "recipient": y, "status": "pending/approved/paid"}
}


# -------------------------------------------------
# Routes
# -------------------------------------------------
@router.get("/")
def get_treasury_status():
    """
    Return current treasury state and aggregate ledger data.
    """
    try:
        pools = getattr(ledger.wecoin, "pools", {})
        total_balance = sum(ledger.wecoin.balances.values()) if hasattr(ledger.wecoin, "balances") else 0
        return {
            "ok": True,
            "treasury_funds": treasury_state["funds"],
            "allocations": treasury_state["allocations"],
            "ledger_total_balance": total_balance,
            "pools": {name: len(meta.get("members", [])) for name, meta in pools.items()},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Treasury status failed: {e}")


@router.post("/deposit/{user_id}/{amount}")
def deposit(user_id: str, amount: float):
    """
    Deposit an amount from a user's ledger account into the treasury.
    """
    try:
        if user_id not in ledger.wecoin.balances:
            raise HTTPException(status_code=404, detail="User not found in ledger")

        if ledger.wecoin.balances[user_id] < amount:
            raise HTTPException(status_code=400, detail="Insufficient user funds")

        ledger.wecoin.balances[user_id] -= amount
        treasury_state["funds"] += amount
        return {"ok": True, "treasury_funds": treasury_state["funds"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deposit failed: {e}")


@router.post("/withdraw/{user_id}/{amount}")
def withdraw(user_id: str, amount: float):
    """
    Withdraw funds from treasury to a user's ledger balance.
    """
    try:
        if treasury_state["funds"] < amount:
            raise HTTPException(status_code=400, detail="Treasury insufficient funds")

        treasury_state["funds"] -= amount
        ledger.wecoin.balances[user_id] = ledger.wecoin.balances.get(user_id, 0) + amount
        return {"ok": True, "treasury_funds": treasury_state["funds"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Withdrawal failed: {e}")


@router.post("/allocate")
def allocate_funds(
    proposal_id: str = Query(...),
    recipient: str = Query(...),
    amount: float = Query(...),
    allocator_id: str = Query(...)
):
    """
    Allocate funds to a recipient (DAO proposal workflow).
    Requires PoH Tier-3 verification.
    """
    if not has_nft(allocator_id, "PoH", min_level=3):
        raise HTTPException(status_code=401, detail="PoH Tier-3 required for fund allocation")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    if treasury_state["funds"] < amount:
        raise HTTPException(status_code=400, detail="Insufficient treasury funds")

    if proposal_id in treasury_state["allocations"]:
        raise HTTPException(status_code=400, detail="Proposal already allocated")

    treasury_state["allocations"][proposal_id] = {
        "amount": amount,
        "recipient": recipient,
        "status": "pending",
        "approved_by": allocator_id,
    }

    return {"ok": True, "proposal_id": proposal_id, "status": "pending"}


@router.post("/payout/{proposal_id}")
def execute_payout(proposal_id: str, executor_id: str = Query(...)):
    """
    Execute an approved allocation payout.
    Requires PoH Tier-3 verification.
    """
    if not has_nft(executor_id, "PoH", min_level=3):
        raise HTTPException(status_code=401, detail="PoH Tier-3 required for payouts")

    alloc = treasury_state["allocations"].get(proposal_id)
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    if alloc["status"] == "paid":
        return {"ok": True, "message": "Already paid"}

    amount = alloc["amount"]
    recipient = alloc["recipient"]

    if treasury_state["funds"] < amount:
        raise HTTPException(status_code=400, detail="Insufficient treasury funds")

    # Perform payout
    ledger.wecoin.balances[recipient] = ledger.wecoin.balances.get(recipient, 0) + amount
    treasury_state["funds"] -= amount
    alloc["status"] = "paid"
    alloc["executed_by"] = executor_id

    return {
        "ok": True,
        "proposal_id": proposal_id,
        "recipient": recipient,
        "amount": amount,
        "treasury_remaining": treasury_state["funds"],
    }
