"""
PoHRuntime
- Proof of Humanity runtime
- Handles tiered verification (Tier1, Tier2, Tier3)
- Provides hooks for juror disputes and live Tier3 conferences
"""

import time
from typing import Dict, Any, Optional


class PoHRuntime:
    def __init__(self):
        self.executor = None  # backref to executor (wired in attach_executor)
        self.tier2_queue: Dict[str, Dict[str, Any]] = {}  # user_id -> request metadata
        self.tier3_queue: Dict[str, Dict[str, Any]] = {}  # user_id -> request metadata

    def attach_executor(self, executor):
        """Link PoH runtime back to main executor for juror/validator calls."""
        self.executor = executor

    # ------------------------------------------------------------------
    # Tier1 bootstrap (basic ID check)
    # ------------------------------------------------------------------
    def request_tier1(self, user_id: str) -> Dict[str, Any]:
        """Simplified: Tier1 auto-approves for now (bootstrap)."""
        if not self.executor:
            return {"ok": False, "error": "executor_not_attached"}
        user = self.executor.state["users"].get(user_id)
        if not user:
            return {"ok": False, "error": "user_not_found"}
        user["poh_level"] = 1
        return {"ok": True, "tier": 1}

    # ------------------------------------------------------------------
    # Tier2 verification (juror vote flow)
    # ------------------------------------------------------------------
    def request_tier2(self, user_id: str) -> Dict[str, Any]:
        """
        Submit Tier2 request: auto-queued for juror voting.
        Jurors will be polled asynchronously (executor.juror_vote).
        """
        if not self.executor:
            return {"ok": False, "error": "executor_not_attached"}
        self.tier2_queue[user_id] = {
            "requested": time.time(),
            "votes": {},
            "status": "pending",
        }
        return {"ok": True, "queued": True, "tier": 2}

    def process_tier2_queue(self, cid_exists_fn=None) -> None:
        """
        Background worker (called from weall_api.py replicate thread).
        Checks for queued Tier2 requests and finalizes once quorum is met.
        """
        if not self.executor:
            return
        for user_id, req in list(self.tier2_queue.items()):
            if req["status"] != "pending":
                continue
            # Check if enough jurors voted
            votes = req["votes"]
            quorum = int(self.executor.poh_requirements.get("juror", 3))
            if len(votes) >= quorum:
                yes = sum(1 for v in votes.values() if v == "yes")
                no = sum(1 for v in votes.values() if v == "no")
                if yes > no:
                    self.executor.state["users"][user_id]["poh_level"] = 2
                    req["status"] = "approved"
                else:
                    req["status"] = "rejected"

    # ------------------------------------------------------------------
    # Tier3 verification (live video conference with jurors)
    # ------------------------------------------------------------------
    def request_tier3(self, user_id: str) -> Dict[str, Any]:
        """
        Tier3 requires live conference with jurors.
        For MVP, we just queue the request and auto-approve after a delay.
        """
        if not self.executor:
            return {"ok": False, "error": "executor_not_attached"}
        self.tier3_queue[user_id] = {
            "requested": time.time(),
            "status": "pending",
        }
        return {"ok": True, "queued": True, "tier": 3}

    def process_tier3_queue(self) -> None:
        """
        Simplified: auto-approve Tier3 requests after 60s "conference".
        Later this will tie into real video session logic.
        """
        if not self.executor:
            return
        for user_id, req in list(self.tier3_queue.items()):
            if req["status"] != "pending":
                continue
            if time.time() - req["requested"] > 60:  # simulate 1min conference
                self.executor.state["users"][user_id]["poh_level"] = 3
                req["status"] = "approved"
