"""
GovernanceState – proposals, votes, quorum, enactment
- Simple YES/NO/ABSTAIN voting
- Quorum + majority threshold
- Pallet execution hook: call registered handlers with params
"""

from typing import Dict, Any, Callable, Optional
from collections import defaultdict

YES = "yes"
NO = "no"
ABSTAIN = "abstain"

DEFAULT_QUORUM = 3
DEFAULT_THRESHOLD = 0.5  # >50% yes among yes+no

class GovernanceState:
    def __init__(self):
        self.proposals: Dict[int, Dict[str, Any]] = {}
        self.next_id: int = 1
        # pallet_name -> callable(params) -> dict
        self.pallets: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    # ----- pallet registry -----
    def register_pallet(self, name: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self.pallets[name] = handler

    # ----- proposals -----
    def create_proposal(
        self,
        user_id: str,
        title: str,
        description: str,
        pallet_reference: str = "",
        params: Optional[Dict[str, Any]] = None,
        quorum: int = DEFAULT_QUORUM,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> Dict[str, Any]:
        pid = self.next_id
        self.next_id += 1
        self.proposals[pid] = {
            "id": pid,
            "creator": user_id,
            "title": title,
            "description": description,
            "pallet": pallet_reference,  # e.g., "Treasury.allocate" or "Params.set"
            "params": params or {},
            "votes": {},  # voter_id -> YES|NO|ABSTAIN
            "status": "open",
            "quorum": int(quorum),
            "threshold": float(threshold),
        }
        return {"ok": True, "id": pid}

    def cast_vote(self, user_id: str, proposal_id: int, option: str) -> Dict[str, Any]:
        if proposal_id not in self.proposals:
            return {"ok": False, "error": "proposal_not_found"}
        if option not in (YES, NO, ABSTAIN):
            return {"ok": False, "error": "invalid_option"}

        p = self.proposals[proposal_id]
        if p["status"] != "open":
            return {"ok": False, "error": "proposal_closed"}

        if user_id in p["votes"]:
            return {"ok": False, "error": "already_voted"}

        p["votes"][user_id] = option
        # Check for quorum & majority
        self._maybe_enact(p)
        return {"ok": True, "votes": dict(p["votes"]), "status": p["status"]}

    def list_proposals(self):
        return list(self.proposals.values())

    # ----- internals -----
    def _maybe_enact(self, p: Dict[str, Any]) -> None:
        votes = p["votes"]
        if len(votes) < p["quorum"]:
            return  # not enough votes yet

        counts = defaultdict(int)
        for v in votes.values():
            counts[v] += 1

        yes = counts[YES]
        no = counts[NO]
        total_effective = yes + no
        if total_effective == 0:
            # All abstain: fail by default
            p["status"] = "rejected:all_abstain"
            return

        if (yes / total_effective) > p["threshold"]:
            # Enact!
            result = self._execute_pallet(p.get("pallet", ""), p.get("params", {}))
            p["status"] = f"enacted:{result.get('status','ok')}"
            p["result"] = result
        else:
            p["status"] = "rejected:threshold"

    def _execute_pallet(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        name forms:
          "" -> no-op
          "Treasury.allocate"
          "Treasury.reclaim"
          "Params.set"
        """
        if not name:
            return {"status": "noop"}

        # split "Namespace.Action"
        try:
            ns, action = name.split(".", 1)
        except ValueError:
            ns, action = name, ""

        handler = self.pallets.get(ns)
        if not handler:
            return {"status": "no_handler", "pallet": ns}

        # Pass action inside params to the handler
        call_params = dict(params or {})
        call_params["_action"] = action
        try:
            result = handler(call_params)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}
