# weall_node/weall_runtime/governance.py
"""
GovernanceRuntime:
- Proposal registry
- Voting with quorum/threshold (threshold currently unused in MVP)
- Enactment hooks (Treasury.allocate, Params.set, Governance.set_rules)

Executor injects/shared GLOBAL_PARAMS from its own constants.
"""

import time
from typing import Dict, Any

# This dict is overwritten by the executor at construction time to keep
# parameters in sync across the whole runtime.
GLOBAL_PARAMS: Dict[str, Any] = {
    "quorum": 3,
    "threshold": 0.5,
    "juror_reward": 2,
    "juror_slash": 1,
    "author_slash": 5,
    "profile_slash": 10,
    "block_reward": 100,  # total block reward
    "block_rep_reward": 2,  # rep reward for block proposer
    "validator_slash": 5,  # rep penalty for misbehavior
    "operator_reward_online": 1,  # rep reward per uptime check
    "operator_slash_offline": 1,  # rep penalty for missed uptime
    "operator_slash_missing": 2,  # rep penalty for missing CID
    "operator_reward_storage_check": 1,  # rep reward for passing PoS challenge
}


class GovernanceRuntime:
    def __init__(self):
        self.proposals: Dict[int, Dict[str, Any]] = {}
        self.next_proposal_id: int = 1
        self.ledger = None  # attached by executor

    # ------------------------
    # Proposal lifecycle
    # ------------------------
    def propose(
        self, creator: str, title: str, description: str, pallet_ref: str, params=None
    ):
        pid = self.next_proposal_id
        self.next_proposal_id += 1
        prop = {
            "id": pid,
            "creator": creator,
            "title": title,
            "description": description,
            "pallet": pallet_ref,
            "params": dict(params or {}),
            "votes": {},
            "status": "open",
            "created_at": time.time(),
        }
        self.proposals[pid] = prop
        return prop

    def vote(self, user_id: str, proposal_id: int, vote_option: str):
        prop = self.proposals.get(proposal_id)
        if not prop or prop["status"] != "open":
            return {"ok": False, "error": "proposal_closed_or_missing"}

        if user_id in prop["votes"]:
            return {"ok": False, "error": "already_voted"}

        prop["votes"][user_id] = vote_option

        # Check quorum only (threshold reserved for later use)
        if len(prop["votes"]) >= int(GLOBAL_PARAMS.get("quorum", 3)):
            self._enact(prop)

        return {"ok": True, "votes": prop["votes"], "status": prop["status"]}

    # ------------------------
    # Enactment
    # ------------------------
    def _enact(self, prop: Dict[str, Any]) -> None:
        pallet = prop["pallet"]
        params = prop.get("params", {})

        if pallet == "Treasury.allocate":
            pool = params.get("pool")
            amt = float(params.get("amount", 0))
            if self.ledger is not None:
                self.ledger.mint(pool, amt)
            prop["status"] = "enacted"

        elif pallet == "Params.set":
            GLOBAL_PARAMS.update(params)
            prop["status"] = "enacted"

        elif pallet == "Governance.set_rules":
            GLOBAL_PARAMS.update(params)
            prop["status"] = "enacted"

        else:
            prop["status"] = "rejected: unknown_pallet"

    # ------------------------
    # Wire dependencies
    # ------------------------
    def attach_ledger(self, ledger):
        self.ledger = ledger
