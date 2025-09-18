# weall_runtime/governance.py
"""
Simplified governance system for WeAll.
- 1 identity = 1 vote
- Simple majority wins
- No quadratic voting, no stability weighting
- Supports proposal creation, voting, closing, and optional enactment

Dependencies:
- A storage client (e.g. weall_runtime.storage.IPFSClient) for description storage.
- A ledger-like object if actions require transfers (optional).
"""

import time
import uuid
import threading
from typing import Dict, Any, Optional, List


class ProposalStatus:
    OPEN = "open"
    CLOSED = "closed"
    EXECUTED = "executed"
    REJECTED = "rejected"


class GovernanceError(Exception):
    pass


class Proposal:
    def __init__(self, proposer: str, title: str, description_cid: str, action: Dict[str, Any], duration_seconds: int):
        self.id = str(uuid.uuid4())
        self.proposer = proposer
        self.title = title
        self.description_cid = description_cid
        self.action = action
        self.created_at = int(time.time())
        self.expires_at = self.created_at + duration_seconds
        self.status = ProposalStatus.OPEN

        # votes: {"yes": set(user_ids), "no": set(user_ids)}
        self.votes = {"yes": set(), "no": set()}
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        return self.status == ProposalStatus.OPEN and int(time.time()) < self.expires_at

    def add_vote(self, user_id: str, choice: str) -> None:
        if not self.is_open():
            raise GovernanceError("proposal_closed_or_expired")
        choice = choice.lower()
        if choice not in ("yes", "no"):
            raise GovernanceError("invalid_choice")

        with self._lock:
            # remove from both tallies in case user changes vote
            self.votes["yes"].discard(user_id)
            self.votes["no"].discard(user_id)
            self.votes[choice].add(user_id)


class Governance:
    def __init__(self, storage_client, ledger: Optional[object] = None, quorum_fraction: float = 0.0):
        """
        storage_client: expects add_str(content)->cid, get_str(cid)->content
        ledger: optional, used for proposals that transfer funds
        quorum_fraction: optional, fraction of eligible voters required
        """
        self._storage = storage_client
        self._ledger = ledger
        self._proposals: Dict[str, Proposal] = {}
        self._lock = threading.Lock()
        self._quorum_fraction = float(quorum_fraction)

    # --------------------------
    # Proposal lifecycle
    # --------------------------
    def propose(self, proposer_id: str, title: str, description_text: str, action: Optional[Dict[str, Any]] = None, duration_seconds: int = 7 * 24 * 3600) -> str:
        cid = self._storage.add_str(description_text)
        prop = Proposal(proposer_id, title, cid, action or {}, duration_seconds)
        with self._lock:
            self._proposals[prop.id] = prop
        return prop.id

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        with self._lock:
            return self._proposals.get(proposal_id)

    def list_proposals(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": p.id,
                    "title": p.title,
                    "proposer": p.proposer,
                    "status": p.status,
                    "created_at": p.created_at,
                    "expires_at": p.expires_at,
                    "votes_yes": len(p.votes["yes"]),
                    "votes_no": len(p.votes["no"]),
                }
                for p in self._proposals.values()
            ]

    # --------------------------
    # Voting
    # --------------------------
    def vote(self, voter_id: str, proposal_id: str, choice: str) -> None:
        prop = self.get_proposal(proposal_id)
        if not prop:
            raise GovernanceError("proposal_not_found")
        prop.add_vote(voter_id, choice)

    # --------------------------
    # Tallying
    # --------------------------
    def tally(self, proposal_id: str) -> Dict[str, Any]:
        prop = self.get_proposal(proposal_id)
        if not prop:
            raise GovernanceError("proposal_not_found")

        yes = len(prop.votes["yes"])
        no = len(prop.votes["no"])
        total = yes + no

        passes_quorum = True
        if self._quorum_fraction > 0:
            # approximate eligible = yes+no voters for simplicity
            eligible_sum = max(total, 1)
            passes_quorum = (total / eligible_sum) >= self._quorum_fraction

        outcome = "tie"
        if yes > no:
            outcome = "passed"
        elif no > yes:
            outcome = "rejected"

        return {
            "yes": yes,
            "no": no,
            "total_votes": total,
            "passes_quorum": passes_quorum,
            "outcome": outcome,
        }

    # --------------------------
    # Enactment
    # --------------------------
    def enact(self, proposal_id: str) -> Dict[str, Any]:
        prop = self.get_proposal(proposal_id)
        if not prop:
            raise GovernanceError("proposal_not_found")

        tally = self.tally(proposal_id)
        if not tally["passes_quorum"]:
            prop.status = ProposalStatus.REJECTED
            return {"ok": False, "reason": "no_quorum", "tally": tally}

        if tally["outcome"] != "passed":
            prop.status = ProposalStatus.REJECTED
            return {"ok": False, "reason": "not_approved", "tally": tally}

        # handle action if present
        action = prop.action
        try:
            if action and action.get("type") == "transfer" and self._ledger:
                from_id = action.get("from")
                to_id = action.get("to")
                amount = float(action.get("amount", 0.0))
                ok = False
                if from_id and to_id and amount > 0:
                    ok = self._ledger.transfer(from_id, to_id, amount)
                if not ok:
                    prop.status = ProposalStatus.REJECTED
                    return {"ok": False, "reason": "transfer_failed", "tally": tally}

            prop.status = ProposalStatus.EXECUTED
            return {"ok": True, "tally": tally}
        except Exception as e:
            prop.status = ProposalStatus.REJECTED
            return {"ok": False, "reason": str(e), "tally": tally}
