# weall_node/api/consensus.py
from fastapi import APIRouter, HTTPException
from ..weall_executor import executor

router = APIRouter(prefix="/consensus", tags=["consensus"])


@router.get("/status")
def status():
    """Quick health + head height for polling."""
    return executor.get_health()


@router.get("/proposals")
def list_proposals():
    """Inspect current proposals (ids, votes, status)."""
    return executor.list_proposals()


@router.post("/propose/{proposer_id}")
def propose(proposer_id: str):
    """
    Move mempool txs into a block proposal. Does NOT commit.
    Auto-self-votes if proposer_id is a validator.
    """
    res = executor.propose_block(proposer_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "propose_failed"))
    return res


@router.post("/vote/{proposal_id}/{validator_id}")
def vote(proposal_id: str, validator_id: str):
    """
    Cast a validator vote. Finalizes automatically on quorum.
    """
    res = executor.vote_block(validator_id, proposal_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "vote_failed"))
    return res
