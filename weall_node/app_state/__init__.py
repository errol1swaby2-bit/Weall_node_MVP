import json, os
from .chain import ChainState
from .ledger import LedgerState

# ------------------------
# Core State
# ------------------------
chain = ChainState()
ledger = LedgerState(chain)

# ------------------------
# Node
# ------------------------
class Node:
    def __init__(self, ledger: LedgerState):
        self.ledger = ledger
        self.peers = []

    def register_peer(self, peer_url: str):
        if not peer_url or not peer_url.startswith("http"):
            raise ValueError("Invalid peer_url")
        if peer_url not in self.peers:
            self.peers.append(peer_url)
        return self.peers

node = Node(ledger)

# ------------------------
# Governance placeholder
# ------------------------
proposals = {}
proposal_counter = 1
votes = {}

def propose(user_id: str, title: str, description: str):
    global proposal_counter
    pid = proposal_counter
    proposals[pid] = {"user": user_id, "title": title, "description": description, "votes": 0}
    proposal_counter += 1
    return {"ok": True, "proposal_id": pid}

def vote(user_id: str, proposal_id: int, approve: bool):
    if proposal_id not in proposals:
        return {"ok": False, "error": "proposal_not_found"}
    votes.setdefault(proposal_id, {})
    votes[proposal_id][user_id] = approve
    total = sum(1 if v else -1 for v in votes[proposal_id].values())
    proposals[proposal_id]["votes"] = total
    return {"ok": True, "votes": total}

class Governance:
    propose = staticmethod(propose)
    vote = staticmethod(vote)
    proposals = proposals

governance = Governance()
