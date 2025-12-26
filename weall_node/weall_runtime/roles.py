# weall_node/weall_runtime/roles.py
from __future__ import annotations

"""
WeAll Roles & Capability Gate (Spec-aligned)

Spec v2.1 alignment:
- Tier 0: view-only
- Tier 1: like + comment
- Tier 2: post + vote + join groups (and includes like/comment)
- Tier 3: steward extensions (create groups/proposals/transfers + opt-in duties)

Also preserves runtime compatibility:
- NodeKind.PUBLIC_GATEWAY exists (node_config.py expects it)
- capability_matrix_by_tier and capability_matrix_full_example exist (tests expect them)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set


class PoHTier(int, Enum):
    TIER0 = 0
    TIER1 = 1
    TIER2 = 2
    TIER3 = 3


class Capability(str, Enum):
    # Viewing
    VIEW_PUBLIC_CONTENT = "view_public_content"
    VIEW_GROUP_CONTENT = "view_group_content"

    # Posting & interaction
    CREATE_POST = "create_post"
    COMMENT = "comment"
    LIKE = "like"
    FLAG_VIOLATION = "flag_violation"
    DELETE_OWN_CONTENT = "delete_own_content"
    EDIT_OWN_CONTENT = "edit_own_content"

    # Groups
    JOIN_GROUPS = "join_groups"
    LEAVE_GROUPS = "leave_groups"
    CREATE_GROUP = "create_group"

    # Disputes
    VIEW_DISPUTES = "view_disputes"
    OPEN_DISPUTE = "open_dispute"
    SUBMIT_EVIDENCE = "submit_evidence"

    # Governance
    VIEW_GOVERNANCE = "view_governance"
    VOTE_GOVERNANCE = "vote_governance"
    CREATE_GOVERNANCE_PROPOSAL = "create_governance_proposal"

    # Treasury / rewards
    VIEW_TREASURY = "view_treasury"
    CREATE_TREASURY_TRANSFER = "create_treasury_transfer"
    CLAIM_REWARDS = "claim_rewards"
    EARN_CREATOR_REWARDS = "earn_creator_rewards"

    # Opt-in “work” roles (Tier3)
    SERVE_AS_JUROR = "serve_as_juror"
    ACT_AS_EMISSARY = "act_as_emissary"

    # Node / infra
    RUN_NODE = "run_node"
    OPERATE_GATEWAY = "operate_gateway"
    OPERATE_COMMUNITY_NODE = "operate_community_node"
    RUN_VALIDATOR = "run_validator"
    FINALITY_VOTE = "finality_vote"


@dataclass(frozen=True)
class HumanRoleFlags:
    wants_creator: bool = True
    wants_juror: bool = False
    wants_operator: bool = False
    wants_validator: bool = False
    wants_emissary: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return {
            "wants_creator": bool(self.wants_creator),
            "wants_juror": bool(self.wants_juror),
            "wants_operator": bool(self.wants_operator),
            "wants_validator": bool(self.wants_validator),
            "wants_emissary": bool(self.wants_emissary),
        }

    @classmethod
    def from_any(cls, obj: object) -> "HumanRoleFlags":
        if isinstance(obj, HumanRoleFlags):
            return obj
        if isinstance(obj, dict):
            return cls(
                wants_creator=bool(obj.get("wants_creator", True)),
                wants_juror=bool(obj.get("wants_juror", False)),
                wants_operator=bool(obj.get("wants_operator", False)),
                wants_validator=bool(obj.get("wants_validator", False)),
                wants_emissary=bool(obj.get("wants_emissary", False)),
            )
        return cls()


class NodeKind(str, Enum):
    # legacy/deployment-ish
    LIGHT = "light"
    FULL = "full"
    VALIDATOR = "validator"
    OPERATOR = "operator"

    # topology kinds
    OBSERVER_CLIENT = "observer_client"
    PUBLIC_GATEWAY = "public_gateway"
    VALIDATOR_NODE = "validator_node"
    COMMUNITY_NODE = "community_node"


@dataclass(frozen=True)
class RoleProfile:
    poh_tier: PoHTier
    flags: HumanRoleFlags
    node_kind: NodeKind
    capabilities: FrozenSet[Capability]


# -----------------------
# Base capabilities by tier (Spec-aligned)
# -----------------------

_TIER0_BASE: FrozenSet[Capability] = frozenset(
    {
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GOVERNANCE,
        Capability.VIEW_DISPUTES,
        Capability.VIEW_TREASURY,
    }
)

# ✅ Spec: Tier1 can like/comment, but NOT post/vote/join groups
_TIER1_BASE: FrozenSet[Capability] = frozenset(
    {
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GROUP_CONTENT,
        Capability.LIKE,
        Capability.COMMENT,
        Capability.VIEW_GOVERNANCE,
        Capability.VIEW_DISPUTES,
        Capability.VIEW_TREASURY,
    }
)

# ✅ Spec: Tier2 can post + vote + join groups (+ like/comment)
_TIER2_BASE: FrozenSet[Capability] = frozenset(
    {
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GROUP_CONTENT,
        Capability.CREATE_POST,
        Capability.COMMENT,
        Capability.LIKE,
        Capability.FLAG_VIOLATION,
        Capability.JOIN_GROUPS,
        Capability.LEAVE_GROUPS,
        Capability.OPEN_DISPUTE,
        Capability.SUBMIT_EVIDENCE,
        Capability.VOTE_GOVERNANCE,
        Capability.VIEW_GOVERNANCE,
        Capability.VIEW_DISPUTES,
        Capability.CLAIM_REWARDS,
        Capability.VIEW_TREASURY,
        Capability.DELETE_OWN_CONTENT,
        Capability.EDIT_OWN_CONTENT,
    }
)

# Tier3 = Tier2 + steward actions
_TIER3_BASE: FrozenSet[Capability] = frozenset(
    set(_TIER2_BASE)
    | {
        Capability.CREATE_GROUP,
        Capability.CREATE_GOVERNANCE_PROPOSAL,
        Capability.CREATE_TREASURY_TRANSFER,
    }
)

_BASE_CAPS: Dict[PoHTier, FrozenSet[Capability]] = {
    PoHTier.TIER0: _TIER0_BASE,
    PoHTier.TIER1: _TIER1_BASE,
    PoHTier.TIER2: _TIER2_BASE,
    PoHTier.TIER3: _TIER3_BASE,
}


def compute_effective_role_profile(
    poh_tier: PoHTier | int,
    flags: Optional[HumanRoleFlags] = None,
    node_kind: NodeKind = NodeKind.FULL,
) -> RoleProfile:
    tier = PoHTier(int(poh_tier))
    f = flags or HumanRoleFlags()

    caps: Set[Capability] = set(_BASE_CAPS[tier])

    # Creator rewards: Tier2+ by default, removable via wants_creator=False
    if int(tier) >= int(PoHTier.TIER2) and f.wants_creator:
        caps.add(Capability.EARN_CREATOR_REWARDS)
    else:
        caps.discard(Capability.EARN_CREATOR_REWARDS)

    # Opt-in roles require Tier3 + flag
    if tier == PoHTier.TIER3 and f.wants_juror:
        caps.add(Capability.SERVE_AS_JUROR)

    if tier == PoHTier.TIER3 and f.wants_operator:
        caps.update({Capability.RUN_NODE, Capability.OPERATE_GATEWAY, Capability.OPERATE_COMMUNITY_NODE})

    if tier == PoHTier.TIER3 and f.wants_validator:
        caps.add(Capability.RUN_VALIDATOR)
        caps.add(Capability.FINALITY_VOTE)

    if tier == PoHTier.TIER3 and f.wants_emissary:
        caps.add(Capability.ACT_AS_EMISSARY)

    return RoleProfile(poh_tier=tier, flags=f, node_kind=node_kind, capabilities=frozenset(caps))


def capability_matrix_by_tier() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for t in (PoHTier.TIER0, PoHTier.TIER1, PoHTier.TIER2, PoHTier.TIER3):
        prof = compute_effective_role_profile(t)
        out[str(int(t))] = sorted([c.value for c in prof.capabilities])
    return out


def capability_matrix_full_example() -> Dict[str, Dict[str, List[str]]]:
    scenarios = {
        "default": HumanRoleFlags(),
        "creator_opt_out": HumanRoleFlags(wants_creator=False),
        "juror": HumanRoleFlags(wants_juror=True),
        "operator": HumanRoleFlags(wants_operator=True),
        "validator": HumanRoleFlags(wants_validator=True),
        "emissary": HumanRoleFlags(wants_emissary=True),
    }

    out: Dict[str, Dict[str, List[str]]] = {}
    for t in (PoHTier.TIER0, PoHTier.TIER1, PoHTier.TIER2, PoHTier.TIER3):
        tier_key = str(int(t))
        out[tier_key] = {}
        for name, fl in scenarios.items():
            prof = compute_effective_role_profile(t, fl)
            out[tier_key][name] = sorted([c.value for c in prof.capabilities])
    return out
