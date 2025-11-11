"""
weall_node/api/treasury.py
--------------------------------------------------
Unified Treasury API for WeAll Node v1.1
Handles protocol treasury balance, funding proposals, and NFT-based receipts.
Uses the unified executor runtime (no app_state or weall_runtime dependencies).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from ..weall_executor import executor

router = APIRouter()


# ---------------------------------------------------------------
# Data models
# ---------------------------------------------------------------
class Proposal(BaseModel):
    """Simple treasury proposal structure."""

    proposal_id: str
    proposer: str
    amount: float
    description: str
    approved: bool = False
    executed: bool = False


# ---------------------------------------------------------------
# In-memory proposal list (temporary)
# ---------------------------------------------------------------
PROPOSALS: Dict[str, Proposal] = {}


# ---------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------
def _treasury_balance() -> float:
    """Return current treasury balance from executor ledger."""
    return float(executor.ledger.get("treasury_balance", 0.0))


def _update_treasury_balance(amount: float) -> None:
    executor.ledger["treasury_balance"] = _treasury_balance() + amount
    executor.save_state()


# ---------------------------------------------------------------
# Routes
# ---------------------------------------------------------------


@router.get("/balance")
def get_treasury_balance() -> Dict[str, Any]:
    """Return current treasury balance."""
    return {"ok": True, "balance": _treasury_balance()}


@router.post("/deposit")
def deposit_to_treasury(sender: str, amount: float):
    """Simulate deposit to treasury (for testing)."""
    if not executor.transfer_funds(sender, "treasury", amount):
        raise HTTPException(status_code=400, detail="Insufficient funds")
    _update_treasury_balance(amount)
    return {"ok": True, "balance": _treasury_balance()}


@router.post("/propose")
def propose_funding(proposal: Proposal):
    """Submit a new treasury proposal."""
    if proposal.proposal_id in PROPOSALS:
        raise HTTPException(status_code=400, detail="Proposal already exists")
    PROPOSALS[proposal.proposal_id] = proposal
    return {"ok": True, "proposal": proposal}


@router.get("/proposals")
def list_proposals() -> List[Dict[str, Any]]:
    """List all current proposals."""
    return [p.dict() for p in PROPOSALS.values()]


@router.post("/approve/{proposal_id}")
def approve_proposal(proposal_id: str, approver: Optional[str] = None):
    """Approve a funding proposal."""
    if proposal_id not in PROPOSALS:
        raise HTTPException(status_code=404, detail="Proposal not found")
    prop = PROPOSALS[proposal_id]
    prop.approved = True
    return {"ok": True, "proposal": prop}


@router.post("/execute/{proposal_id}")
def execute_proposal(proposal_id: str):
    """
    Execute an approved proposal.
    Deducts amount from treasury and issues an NFT receipt.
    """
    if proposal_id not in PROPOSALS:
        raise HTTPException(status_code=404, detail="Proposal not found")

    prop = PROPOSALS[proposal_id]
    if not prop.approved:
        raise HTTPException(status_code=400, detail="Proposal not approved")
    if prop.executed:
        raise HTTPException(status_code=400, detail="Proposal already executed")

    balance = _treasury_balance()
    if balance < prop.amount:
        raise HTTPException(status_code=400, detail="Insufficient treasury funds")

    # Deduct from treasury balance
    executor.ledger["treasury_balance"] = balance - prop.amount
    executor.save_state()

    # Mint NFT receipt (on-ledger proof of disbursement)
    nft_metadata = f"Treasury grant to {prop.proposer}: {prop.description}"
    receipt = executor.mint_nft(prop.proposer, prop.proposal_id, nft_metadata)

    prop.executed = True
    return {"ok": True, "proposal": prop, "receipt": receipt}


@router.post("/burn/{nft_id}")
def burn_treasury_receipt(nft_id: str):
    """Burn an existing treasury receipt NFT."""
    success = executor.burn_nft(nft_id)
    if not success:
        raise HTTPException(status_code=404, detail="NFT not found or already burned")
    return {"ok": True, "burned": nft_id}
