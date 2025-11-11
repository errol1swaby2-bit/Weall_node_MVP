"""
weall_node/api/ledger.py
--------------------------------------------------
Read-only ledger + cryptographic proofs.
- List commitments signed by the node (epoch Merkle roots)
- Retrieve a Merkle proof for a specific account
- Read-only ledger snapshots
"""

from fastapi import APIRouter, HTTPException
from ..weall_executor import executor

router = APIRouter()


@router.get("/")
def get_full_ledger():
    return {
        "ok": True,
        "block_height": executor.block_height,
        "epoch": executor.epoch,
        "ledger": executor.ledger,
    }


@router.get("/balance/{user_id}")
def get_balance(user_id: str):
    if user_id not in executor.ledger:
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True, "user": user_id, "balance": executor.ledger[user_id]}


@router.get("/stats")
def ledger_stats():
    total_accounts = sum(
        1 for v in executor.ledger.values() if isinstance(v, (int, float))
    )
    total_balance = sum(
        v for v in executor.ledger.values() if isinstance(v, (int, float))
    )
    return {
        "ok": True,
        "accounts": total_accounts,
        "total_balance": total_balance,
        "block_height": executor.block_height,
        "epoch": executor.epoch,
    }


@router.get("/commitments")
def get_commitments():
    """Signed epoch commitments (Merkle roots) with signatures and pubkey."""
    return {"ok": True, "commitments": executor.get_commitments()}


@router.get("/proof/{user_id}")
def merkle_proof(user_id: str):
    """Return Merkle proof for the user's balance under the latest snapshot."""
    return executor.get_merkle_proof(user_id)
