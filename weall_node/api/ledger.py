#!/usr/bin/env python3
"""
Ledger API
------------------------------------
Handles user account creation, deposits, and transfers.
Temporary in-memory ledger with optional blockchain recording.
"""

import logging, time
from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from weall_node.app_state import chain

router = APIRouter(prefix="/ledger", tags=["ledger"])
logger = logging.getLogger("ledger")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Simple in-memory placeholder
LEDGER = {"balances": {}}


# -------------------------------
# Pydantic Models
# -------------------------------
class AccountCreate(BaseModel):
    user_id: str


class DepositRequest(BaseModel):
    user_id: str
    amount: Decimal = Field(gt=0, description="Amount to deposit")


class TransferRequest(BaseModel):
    from_user: str
    to_user: str
    amount: Decimal = Field(gt=0, description="Amount to transfer")


# -------------------------------
# Routes
# -------------------------------
@router.get("/")
def get_ledger_status():
    """Basic health/status endpoint for the ledger module."""
    return {"status": "ok", "message": "Ledger module is active", "accounts": len(LEDGER["balances"])}


@router.post("/create_account")
def create_account(req: AccountCreate):
    """Create a new account with zero balance."""
    uid = req.user_id
    if uid in LEDGER["balances"]:
        raise HTTPException(status_code=400, detail="Account already exists")

    LEDGER["balances"][uid] = Decimal("0")
    logger.info("Created ledger account for %s", uid)
    return {"ok": True, "user_id": uid, "balance": str(LEDGER["balances"][uid])}


@router.get("/balance/{user_id}")
def get_balance(user_id: str):
    """Get the balance of a user account."""
    if user_id not in LEDGER["balances"]:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True, "user_id": user_id, "balance": str(LEDGER["balances"][user_id])}


@router.post("/deposit")
def deposit(req: DepositRequest):
    """Deposit an amount into a user account."""
    if req.user_id not in LEDGER["balances"]:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        amt = Decimal(req.amount)
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="Invalid amount")

    LEDGER["balances"][req.user_id] += amt

    # Record on chain
    tx = {"type": "DEPOSIT", "user": req.user_id, "amount": float(amt), "timestamp": int(time.time())}
    try:
        block = chain.add_block([tx])
        logger.info("Deposit: %s +%s (block %s)", req.user_id, amt, block["hash"])
    except Exception as e:
        logger.warning("Chain record skipped: %s", e)
        block = {"hash": "unrecorded"}

    return {"ok": True, "user_id": req.user_id, "balance": str(LEDGER["balances"][req.user_id]), "block": block["hash"]}


@router.post("/transfer")
def transfer(req: TransferRequest):
    """Transfer funds from one account to another."""
    f, t, amt = req.from_user, req.to_user, Decimal(req.amount)

    if f not in LEDGER["balances"]:
        raise HTTPException(status_code=404, detail="Sender not found")
    if t not in LEDGER["balances"]:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if LEDGER["balances"][f] < amt:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    LEDGER["balances"][f] -= amt
    LEDGER["balances"][t] += amt

    tx = {"type": "TRANSFER", "from": f, "to": t, "amount": float(amt), "timestamp": int(time.time())}
    try:
        block = chain.add_block([tx])
        logger.info("Transfer %s -> %s : %s (block %s)", f, t, amt, block["hash"])
    except Exception as e:
        logger.warning("Chain record skipped: %s", e)
        block = {"hash": "unrecorded"}

    return {
        "ok": True,
        "from_balance": str(LEDGER["balances"][f]),
        "to_balance": str(LEDGER["balances"][t]),
        "block": block["hash"],
    }
