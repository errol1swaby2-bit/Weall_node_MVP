# api/treasury.py
from fastapi import APIRouter, HTTPException
from weall_node.app_state import ledger, chain
from weall_node.weall_runtime.wallet import mint_nft, burn_nft

router = APIRouter(prefix="/treasury", tags=["treasury"])

# -------------------------------------------------------------------
# In-memory treasury (mirrored by chain + ledger)
# -------------------------------------------------------------------
treasury_state = {
    "funds": 0.0,
    "receipts": {}  # user_id -> list of receipt NFT ids
}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _record_block(tx_type: str, payload: dict):
    """Append a treasury transaction block to the chain."""
    block = {
        "ts": int(__import__("time").time()),
        "txs": [{"type": tx_type, "payload": payload}],
        "prev": chain.latest().get("hash", "genesis"),
        "validator": "system",
        "sig": "system-auto",
    }
    import json, hashlib
    raw = json.dumps(block, sort_keys=True).encode()
    block["hash"] = hashlib.sha256(raw).hexdigest()
    chain.blocks.append(block)
    chain.persist()
    return block


# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------

@router.get("/")
def get_treasury_status():
    """Return current treasury funds and receipts summary."""
    return {
        "status": "ok",
        "funds": treasury_state["funds"],
        "receipts": {
            u: len(v) for u, v in treasury_state["receipts"].items()
        },
    }


@router.post("/deposit/{user_id}/{amount}")
def deposit(user_id: str, amount: float):
    """Deposit funds from user's ledger into treasury and mint receipt NFT."""
    # Check balance
    bal = float(ledger.get_balance(user_id))
    if bal < amount:
        raise HTTPException(400, f"Insufficient funds: {bal}")

    # Ledger updates
    ledger.balances[user_id] = bal - amount
    treasury_state["funds"] += amount

    # Mint Treasury Receipt NFT
    nft_id = f"TREASURY_RECEIPT::{user_id}::{int(__import__('time').time())}"
    receipt = mint_nft(user_id, nft_id, metadata=f"Deposit of {amount} WEC")
    treasury_state["receipts"].setdefault(user_id, []).append(nft_id)

    # Record block
    _record_block("TREASURY_DEPOSIT", {"user": user_id, "amount": amount, "nft_id": nft_id})

    return {
        "ok": True,
        "user_id": user_id,
        "amount": amount,
        "treasury_funds": treasury_state["funds"],
        "nft": receipt,
    }


@router.post("/withdraw/{user_id}/{amount}")
def withdraw(user_id: str, amount: float):
    """Withdraw funds from treasury to user's ledger and burn receipt NFT."""
    if treasury_state["funds"] < amount:
        raise HTTPException(400, "Insufficient treasury funds")

    # Reduce treasury
    treasury_state["funds"] -= amount
    ledger.balances[user_id] = ledger.balances.get(user_id, 0) + amount

    # Burn latest treasury receipt if any
    receipts = treasury_state["receipts"].get(user_id, [])
    burned = None
    if receipts:
        nft_id = receipts.pop()  # Burn most recent
        burned = burn_nft(nft_id)

    # Record block
    _record_block("TREASURY_WITHDRAW", {"user": user_id, "amount": amount, "burned": burned})

    return {
        "ok": True,
        "user_id": user_id,
        "amount": amount,
        "treasury_funds": treasury_state["funds"],
        "burned_receipt": burned,
    }
