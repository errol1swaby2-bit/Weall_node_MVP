# tests/test_governance_basic.py

import pathlib
import sys

import pytest
from fastapi import HTTPException

# Ensure repo root (containing inner weall_node package) is on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weall_node.weall_executor import executor
from weall_node.api.governance import (
    Proposal,
    ProposalCreate,
    ProposalVoteRequest,
    create_proposal,
    vote_proposal,
    close_proposal,
)


# ============================================================
# Helpers / fixtures
# ============================================================

def _reset_governance_state() -> None:
    """
    Ensure executor.ledger['governance']['proposals'] is empty.

    We call this before each test so that tests don't interfere with
    each other via shared in-memory state.
    """
    gov_root = executor.ledger.setdefault("governance", {})
    gov_root["proposals"] = {}


@pytest.fixture(autouse=True)
def clean_governance():
    _reset_governance_state()
    yield
    _reset_governance_state()


def _basic_proposal_payload(created_by: str = "@alice") -> ProposalCreate:
    return ProposalCreate(
        title="Test proposal",
        description="Just a test",
        created_by=created_by,
        type="signal",
        options=["yes", "no", "abstain"],
        duration_sec=60,
        # group_id and audience have usable defaults; we can omit them
    )


# ============================================================
# Tests
# ============================================================

def test_create_proposal_initial_state():
    """
    Creating a proposal should:
    - Succeed with ok=True
    - Produce an open Proposal
    - Initialize tallies to 0 for each option
    - Start with no votes
    """
    payload = _basic_proposal_payload()
    resp = create_proposal(payload, proposer_id="@alice")

    assert resp["ok"] is True
    proposal = resp["proposal"]
    assert isinstance(proposal, Proposal)

    # Basic fields
    assert proposal.title == payload.title
    assert proposal.created_by == "@alice"
    assert proposal.status == "open"

    # Options + tallies
    assert proposal.options == ["yes", "no", "abstain"]
    assert proposal.tallies == {opt: 0 for opt in proposal.options}

    # No votes yet
    assert proposal.votes == {}


def test_single_vote_counts_once():
    """
    A single vote should:
    - Record the voter's choice
    - Increment the correct tally
    - Leave other tallies at 0
    - Keep the proposal open
    """
    payload = _basic_proposal_payload()
    create_resp = create_proposal(payload, proposer_id="@alice")
    prop_id = create_resp["proposal"].id

    vote_payload = ProposalVoteRequest(choice="yes")
    vote_resp = vote_proposal(prop_id, vote_payload, voter_id="@bob")

    proposal = vote_resp["proposal"]

    assert proposal.status == "open"
    assert proposal.votes == {"@bob": "yes"}
    assert proposal.tallies["yes"] == 1
    assert proposal.tallies["no"] == 0
    assert proposal.tallies["abstain"] == 0


def test_double_vote_updates_not_double_counts():
    """
    If a voter changes their mind:
    - Their previous tally should be decremented
    - Their new choice should be incremented
    - Final tallies should reflect only the latest choice
    """
    payload = _basic_proposal_payload()
    create_resp = create_proposal(payload, proposer_id="@alice")
    prop_id = create_resp["proposal"].id

    # First vote: yes
    vote_proposal(prop_id, ProposalVoteRequest(choice="yes"), voter_id="@bob")

    # Second vote: no (same voter)
    resp = vote_proposal(prop_id, ProposalVoteRequest(choice="no"), voter_id="@bob")
    proposal = resp["proposal"]

    assert proposal.votes == {"@bob": "no"}
    assert proposal.tallies["yes"] == 0  # decremented back to 0
    assert proposal.tallies["no"] == 1
    assert proposal.tallies["abstain"] == 0


def test_invalid_choice_rejected():
    """
    Voting with a choice not in the proposal's options should:
    - Raise HTTPException 400
    - Not modify votes or tallies
    """
    payload = _basic_proposal_payload()
    create_resp = create_proposal(payload, proposer_id="@alice")
    prop_id = create_resp["proposal"].id

    # Snapshot tallies before invalid vote
    before = create_resp["proposal"].tallies.copy()

    with pytest.raises(HTTPException) as excinfo:
        vote_proposal(
            prop_id, ProposalVoteRequest(choice="maybe"), voter_id="@bob"
        )

    assert excinfo.value.status_code == 400

    # Ensure nothing changed in stored proposal
    stored = create_resp["proposal"]
    assert stored.tallies == before
    assert stored.votes == {}


def test_closed_proposal_rejects_votes():
    """
    Once a proposal is closed:
    - status should be 'closed'
    - any further votes should raise HTTPException 400
    """
    payload = _basic_proposal_payload()
    create_resp = create_proposal(payload, proposer_id="@alice")
    prop_id = create_resp["proposal"].id

    # Close the proposal
    close_resp = close_proposal(prop_id, _closer_id="@alice")
    proposal = close_resp["proposal"]
    assert proposal.status == "closed"

    # Voting after close should fail
    with pytest.raises(HTTPException) as excinfo:
        vote_proposal(
            prop_id, ProposalVoteRequest(choice="yes"), voter_id="@bob"
        )

    assert excinfo.value.status_code == 400
