# weall_node/weall_runtime/governance.py
from __future__ import annotations

"""
Runtime governance defaults for WeAll.

This module centralizes the "knobs" used by the node to apply
governance-related rewards and penalties.

Key principles encoded here
---------------------------
1. **WCN is never burned or destructively slashed here.**
   - These parameters do NOT directly move token balances.
   - Any economic flows (WCN) must be implemented in the ledger /
     rewards / treasury layers as explicit transfers, always preserving
     total supply.

2. **Reputation is the primary axis of sanction and reward.**
   - All "*_rep_penalty" and "*_rep_reward" values are intended to be
     applied to a user's reputation score (e.g. via ReputationRuntime),
     not to their token balances.

3. **Compatibility with older "slash" terminology.**
   - Older code and docs used names like "juror_slash" or
     "validator_slash" to refer to penalties.
   - To avoid breaking existing code, we expose read-only aliases for
     those legacy keys, but new code should migrate to the explicit
     "*_rep_penalty" naming.
"""

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Core parameter table
# ---------------------------------------------------------------------------

GOVERNANCE_PARAMS: Dict[str, Any] = {
    # -------------------------------------------------
    # Jurors (reputation-only economics)
    # -------------------------------------------------
    # Reputation reward per correct/majority-aligned decision
    "juror_rep_reward": 2,
    # Reputation penalty per clearly harmful / minority-against-evidence decision
    "juror_rep_penalty": 1,

    # -------------------------------------------------
    # Authors / profiles (reputation-only penalties)
    # -------------------------------------------------
    # Reputation penalty for content / behavior that results in a negative verdict
    "author_rep_penalty": 5,
    # Reputation penalty for identity-level sanctions (e.g. repeated abuse)
    "profile_rep_penalty": 10,

    # -------------------------------------------------
    # Block & operator rewards (WCN + reputation)
    # -------------------------------------------------
    # Base block reward (in WCN) BEFORE any splitting between validator,
    # node operators, jurors, creators, treasury, etc. The actual
    # distribution is handled in the ledger / rewards module.
    "block_reward_wcn": 100,

    # Reputation reward for a validator successfully proposing / validating
    # a block according to consensus rules.
    "validator_rep_reward": 0.5,
    # Reputation penalty for validator misbehavior (e.g. invalid blocks).
    "validator_rep_penalty": 5,

    # Reputation reward for an operator staying online / serving traffic.
    "operator_uptime_rep_reward": 0.5,
    # Reputation penalty for an operator being offline during uptime checks.
    "operator_rep_penalty_offline": 1,
    # Reputation penalty for repeated / severe missed uptime events.
    "operator_rep_penalty_missing": 2,
}


# ---------------------------------------------------------------------------
# Legacy "slash" aliases (reputation only)
# ---------------------------------------------------------------------------
#
# These are provided for backwards compatibility with existing code and
# config that may still reference "juror_slash", "author_slash", etc.
#
# IMPORTANT:
# - They MUST be interpreted as reputation penalties only.
# - New code should use the "*_rep_penalty" and "*_rep_reward" names.
#

# Jurors
GOVERNANCE_PARAMS.setdefault("juror_reward", GOVERNANCE_PARAMS["juror_rep_reward"])
GOVERNANCE_PARAMS.setdefault("juror_slash", GOVERNANCE_PARAMS["juror_rep_penalty"])

# Authors / profiles
GOVERNANCE_PARAMS.setdefault("author_slash", GOVERNANCE_PARAMS["author_rep_penalty"])
GOVERNANCE_PARAMS.setdefault("profile_slash", GOVERNANCE_PARAMS["profile_rep_penalty"])

# Validators
GOVERNANCE_PARAMS.setdefault("validator_slash", GOVERNANCE_PARAMS["validator_rep_penalty"])

# Operators
GOVERNANCE_PARAMS.setdefault(
    "operator_slash_offline", GOVERNANCE_PARAMS["operator_rep_penalty_offline"]
)
GOVERNANCE_PARAMS.setdefault(
    "operator_slash_missing", GOVERNANCE_PARAMS["operator_rep_penalty_missing"]
)


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def get_param(name: str, default: Any | None = None) -> Any:
    """
    Helper to safely access governance parameters.

    This is primarily a convenience for other runtime modules (e.g.
    participation, rewards, disputes) so they don't hard-code magic
    numbers.

    Examples
    --------
    >>> get_param("juror_rep_reward")
    2
    >>> get_param("block_reward_wcn")
    100
    """
    return GOVERNANCE_PARAMS.get(name, default)
