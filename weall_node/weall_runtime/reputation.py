from __future__ import annotations
from typing import Dict, Any
import time

MIN_REP = -1.0
MAX_REP = 1.0


class ReputationRuntime:
    """
    Spec-aligned reputation runtime.

    - Reputation score lives in [-1.0, 1.0].
    - Data stored in state["reputation"].
    - Updates logged in state["rep_events"] for auditability.
    - Thresholds are enforced by callers (API/governance), e.g.:
        >= 0.75 -> Tier-3 style permissions
        -1.0    -> terminal / subject to deletion.
    """

    def __init__(self, state: Dict[str, Any]) -> None:
        # `state` is typically executor.ledger
        self.state = state
        self.state.setdefault("reputation", {})
        self.state.setdefault("rep_events", [])

    def _clamp(self, value: float) -> float:
        if value < MIN_REP:
            return MIN_REP
        if value > MAX_REP:
            return MAX_REP
        return value

    def get(self, user_id: str) -> float:
        return float(self.state["reputation"].get(user_id, 0.0))

    def apply_delta(self, user_id: str, delta: float, reason: str | None = None) -> float:
        """
        Apply a signed delta, clamp to [-1, 1], and record an event.
        Returns the new reputation.
        """
        if not user_id:
            raise ValueError("user_id is required")

        current = float(self.state["reputation"].get(user_id, 0.0))
        new_score = self._clamp(current + float(delta))

        self.state["reputation"][user_id] = new_score
        self.state["rep_events"].append(
            {
                "user": user_id,
                "delta": float(delta),
                "result": new_score,
                "reason": (reason or "unspecified"),
                "ts": int(time.time()),
            }
        )
        return new_score
