# app_state/__init__.py

from collections import defaultdict
import json
import os

# ------------------------
# Ledger
# ------------------------
class Ledger:
    def __init__(self, persist_file=None):
        self.accounts = defaultdict(float)
        self.pools = defaultdict(set)
        self.persist_file = persist_file

    def create_account(self, user_id: str):
        """Ensure an account exists."""
        self.accounts.setdefault(user_id, 0.0)

    def deposit(self, user_id: str, amount: float):
        """Deposit funds into an account."""
        self.create_account(user_id)
        self.accounts[user_id] += amount
        return self.accounts[user_id]

    def transfer(self, from_user: str, to_user: str, amount: float):
        """Transfer funds between accounts if balance allows."""
        self.create_account(from_user)
        self.create_account(to_user)
        if self.accounts[from_user] >= amount:
            self.accounts[from_user] -= amount
            self.accounts[to_user] += amount
            return True
        return False

    def balance(self, user_id: str):
        """Return balance of an account."""
        self.create_account(user_id)
        return self.accounts[user_id]

    def snapshot(self):
        """
        Return a serializable snapshot of the ledger state.
        Also persist to file if persist_file is set.
        """
        if self.persist_file:
            with open(self.persist_file, "w") as f:
                json.dump(self.accounts, f)

        return {
            "accounts": dict(self.accounts),
            "pools": {k: list(v) for k, v in self.pools.items()},
        }

    def load(self):
        """Load ledger state from persist_file, if present."""
        if self.persist_file and os.path.exists(self.persist_file):
            with open(self.persist_file) as f:
                self.accounts = defaultdict(float, json.load(f))


# ------------------------
# Node
# ------------------------
class Node:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.peers = []

    def register_peer(self, peer_url: str):
        """
        Register a peer. Must start with http(s).
        """
        if not peer_url or not peer_url.startswith("http"):
            raise ValueError("Invalid peer_url")
        if peer_url not in self.peers:
            self.peers.append(peer_url)
        return self.peers


# ------------------------
# Proof of Humanity placeholder
# ------------------------
users = {}

def verify_tier1(user: str):
    state = users.setdefault(
        user, {"tier1": False, "tier2_applied": None, "tier2_verified": False, "tier3_verified": False}
    )
    state["tier1"] = True
    return {"user": user, "tier1_verified": True}

def apply_tier2(user: str, evidence: str):
    state = users.setdefault(
        user, {"tier1": False, "tier2_applied": None, "tier2_verified": False, "tier3_verified": False}
    )
    if not state["tier1"]:
        return {"ok": False, "error": "tier1_not_verified"}
    state["tier2_applied"] = evidence
    state["tier2_verified"] = False
    return {"ok": True, "message": "Tier 2 application submitted"}

def verify_tier2(user: str, approver: str, approve: bool):
    state = users.get(user)
    if not state or not state["tier2_applied"]:
        return {"ok": False, "error": "tier2_not_applied"}
    if approve:
        state["tier2_verified"] = True
    return {"ok": True, "tier2_verified": state["tier2_verified"], "approver": approver}

def verify_tier3(user: str, video_proof: str):
    state = users.setdefault(
        user, {"tier1": False, "tier2_applied": None, "tier2_verified": False, "tier3_verified": False}
    )
    if not state["tier2_verified"]:
        return {"ok": False, "error": "tier2_not_verified"}
    state["tier3_verified"] = True
    return {"ok": True, "tier3_verified": True}

def status(user: str):
    state = users.get(user)
    if not state:
        return {
            "user": user,
            "tier1_verified": False,
            "tier2_verified": False,
            "tier3_verified": False,
        }
    return {
        "user": user,
        "tier1_verified": state["tier1"],
        "tier2_verified": state["tier2_verified"],
        "tier3_verified": state["tier3_verified"],
    }

class PoH:
    verify_tier1 = staticmethod(verify_tier1)
    apply_tier2 = staticmethod(apply_tier2)
    verify_tier2 = staticmethod(verify_tier2)
    verify_tier3 = staticmethod(verify_tier3)
    status = staticmethod(status)

poh = PoH()

# Default global state (can be monkeypatched in tests)
ledger = Ledger()
node = Node(ledger)

# Governance placeholder
proposals = {}
proposal_counter = 1
votes = {}

def propose(user_id: str, title: str, description: str):
    global proposal_counter
    pid = proposal_counter
    proposals[pid] = {
        "user": user_id,
        "title": title,
        "description": description,
        "votes": 0,
    }
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

# Expose governance as module-like
class Governance:
    propose = staticmethod(propose)
    vote = staticmethod(vote)
    proposals = proposals

governance = Governance()
