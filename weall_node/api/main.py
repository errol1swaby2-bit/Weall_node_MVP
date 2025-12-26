from __future__ import annotations

from fastapi import FastAPI

# Routers (router-based modules)
from weall_node.api.chain import router as chain_router
from weall_node.api.consensus import router as consensus_router
from weall_node.api.content import router as content_router
from weall_node.api.disputes import router as disputes_router
from weall_node.api.groups import router as groups_router
from weall_node.api.treasury import router as treasury_router

# Some modules in this repo are router-based, others expose functions.
# Governance here is function-based (create_proposal, vote_proposal, etc.)
from weall_node.api.governance import (
    create_proposal,
    vote_proposal,
    close_proposal,
    get_proposal,
    list_proposals,
)

app = FastAPI(title="WeAll Node API", version="0.1.0")

# Include routers
app.include_router(chain_router)
app.include_router(consensus_router)
app.include_router(content_router)
app.include_router(groups_router)
app.include_router(disputes_router)
app.include_router(treasury_router)

# ---- Governance endpoints (function-based module wiring) ----

@app.get("/governance/proposals")
def api_list_proposals():
    return list_proposals()


@app.get("/governance/proposals/{proposal_id}")
def api_get_proposal(proposal_id: str):
    return get_proposal(proposal_id)


@app.post("/governance/proposals")
def api_create_proposal(payload: dict, proposer_id: str):
    # proposer_id is provided as a query param for now
    return create_proposal(payload, proposer_id=proposer_id)


@app.post("/governance/proposals/{proposal_id}/vote")
def api_vote_proposal(proposal_id: str, payload: dict, voter_id: str):
    return vote_proposal(proposal_id, payload, voter_id=voter_id)


@app.post("/governance/proposals/{proposal_id}/close")
def api_close_proposal(proposal_id: str, closer_id: str):
    return close_proposal(proposal_id, _closer_id=closer_id)


@app.get("/health")
def health():
    return {"ok": True}
