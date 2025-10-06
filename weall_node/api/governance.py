#!/usr/bin/env python3
"""
Governance API
------------------------------------
Handles community proposal creation and voting.
Backed by the app_state.governance runtime.
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from weall_node.app_state import governance

router = APIRouter(prefix="/governance", tags=["governance"])
logger = logging.getLogger("governance")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# -------------------------------
# Pydantic Models
# -------------------------------
class ProposalCreate(BaseModel):
    user: str
    title: str
    description: str
    pallet_reference: str

    class Config:
        json_schema_extra = {
            "example": {
                "user": "alice",
                "title": "Increase Block Reward",
                "description": "Proposal to raise validator rewards",
                "pallet_reference": "Treasury",
            }
        }


class VoteCast(BaseModel):
    user: str
    proposal_id: int
    vote: str  # "yes" | "no" | "abstain"

    class Config:
        json_schema_extra = {
            "example": {"user": "bob", "proposal_id": 1, "vote": "yes"}
        }


# -------------------------------
# Routes
# -------------------------------
@router.post("/propose")
def propose(data: ProposalCreate):
    """Submit a new governance proposal."""
    try:
        result = governance.propose(data.user, data.title, data.description, data.pallet_reference)
        logger.info("Proposal created by %s: %s", data.user, data.title)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Internal error in propose(): %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/vote")
def vote(data: VoteCast):
    """Cast a vote on an existing proposal."""
    try:
        result = governance.vote(data.user, data.proposal_id, data.vote)
        logger.info("Vote by %s on proposal %s: %s", data.user, data.proposal_id, data.vote)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Internal error in vote(): %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/proposals")
def list_proposals():
    """List all proposals with their statuses."""
    try:
        return governance.list_proposals()
    except Exception as e:
        logger.exception("Error listing proposals: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list proposals")
