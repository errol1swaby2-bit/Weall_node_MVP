"""
weall_node/weall_runtime/roles.py
--------------------------------------------------
Canonical definition of WeAll network roles & topology.

Implements Full Scope §2: "Network Roles & Topology".

This module stays *pure*: no FastAPI, no database, only
Python data structures and helper functions for other
modules (API, executor, UI) to depend on.

PoH tier rules (per current project spec):
- Tier 1: view-only
- Tier 2: like + comment
- Tier 3: post content (and media uploads)
Moderation is handled by the network via the dispute flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set


# ============================================================
# Base PoH tiers & human "role flags"
# ============================================================

class PoHTier(int, Enum):
    """
    One human → one PoH record → one effective tier.

    Tier 0 is not explicitly in the spec, but it's useful to
    model "Observer" as a pre-PoH state.
    """
    OBSERVER = 0   # unverified, can view public content only
    TIER1 = 1      # email+auth identity, view only
    TIER2 = 2      # can like/comment
    TIER3 = 3      # can post content (and media uploads); can opt into juror/operator/etc


class Capability(str, Enum):
    """
    Fine-grained capabilities that endpoints / frontends can check.

    These are *not* tied to specific URLs: they are semantic
    primitives used across APIs.
    """
    VIEW_PUBLIC_CONTENT = "view_public_content"
    VIEW_GROUP_CONTENT = "view_group_content"

    CREATE_POST = "create_post"
    COMMENT = "comment"
    LIKE = "like"
    FLAG_VIOLATION = "flag_violation"

    JOIN_GROUPS = "join_groups"
    LEAVE_GROUPS = "leave_groups"
    CREATE_GROUP = "create_group"

    VOTE_GOVERNANCE = "vote_governance"
    CREATE_GOVERNANCE_PROPOSAL = "create_governance_proposal"

    OPEN_DISPUTE = "open_dispute"
    SUBMIT_EVIDENCE = "submit_evidence"

    SERVE_AS_JUROR = "serve_as_juror"

    RUN_NODE = "run_node"
    RUN_VALIDATOR = "run_validator"
    OPERATE_GATEWAY = "operate_gateway"
    OPERATE_COMMUNITY_NODE = "operate_community_node"

    ACT_AS_EMISSARY = "act_as_emissary"
    EARN_CREATOR_REWARDS = "earn_creator_rewards"


class NodeKind(str, Enum):
    """
    Topology-level node roles (§2.2 Topology).

    A physical node can be more than one kind, but this is the
    *intended* configuration space.
    """
    OBSERVER_CLIENT = "observer_client"     # browser / light client
    PUBLIC_GATEWAY = "public_gateway"       # exposes HTTP API
    VALIDATOR_NODE = "validator_node"       # participates in consensus
    COMMUNITY_NODE = "community_node"       # private / org node


@dataclass(frozen=True)
class HumanRoleFlags:
    """
    Per-human preference flags. These are *intent* signals; the
    actual ability is the intersection of:

        - PoH tier,
        - Reputation,
        - Network capacity constraints,
        - These flags (juror / validator / operator / emissary / creator).
    """
    wants_juror: bool = False
    wants_validator: bool = False
    wants_operator: bool = False
    wants_emissary: bool = False
    wants_creator: bool = True  # default: everyone may earn creator rewards if eligible


@dataclass(frozen=True)
class EffectiveRoleProfile:
    """
    Effective capabilities for a given human, derived from:

        - PoH tier,
        - human role flags,
        - optional extra constraints (e.g., reputation thresholds).

    This is what API endpoints should *actually check*.
    """
    poh_tier: PoHTier
    flags: HumanRoleFlags
    capabilities: Set[Capability]


# ============================================================
# Capability matrices
# ============================================================

# Base capabilities by PoH tier (no flags, no rep thresholds).
_TIER_BASE_CAPS: Dict[PoHTier, Set[Capability]] = {
    PoHTier.OBSERVER: {
        Capability.VIEW_PUBLIC_CONTENT,
    },
    PoHTier.TIER1: {
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GROUP_CONTENT,
        # Tier 1 = view-only (no join/like/comment/post).
    },
    PoHTier.TIER2: {
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GROUP_CONTENT,

        # Tier 2 = can like + comment
        Capability.LIKE,
        Capability.COMMENT,
        Capability.FLAG_VIOLATION,

        # Community participation (kept at Tier2+)
        Capability.JOIN_GROUPS,
        Capability.LEAVE_GROUPS,

        # Dispute flow participation (moderation happens here)
        Capability.OPEN_DISPUTE,
        Capability.SUBMIT_EVIDENCE,

        # Governance
        Capability.VOTE_GOVERNANCE,
    },
    PoHTier.TIER3: {
        Capability.VIEW_PUBLIC_CONTENT,
        Capability.VIEW_GROUP_CONTENT,

        # Tier 3 = can post content (and uploads, enforced at endpoint level)
        Capability.CREATE_POST,
        Capability.LIKE,
        Capability.COMMENT,
        Capability.FLAG_VIOLATION,

        Capability.JOIN_GROUPS,
        Capability.LEAVE_GROUPS,
        Capability.CREATE_GROUP,

        Capability.OPEN_DISPUTE,
        Capability.SUBMIT_EVIDENCE,

        Capability.VOTE_GOVERNANCE,
        Capability.CREATE_GOVERNANCE_PROPOSAL,
    },
}


def _apply_flags_to_caps(
    tier: PoHTier,
    flags: HumanRoleFlags,
    base_caps: Set[Capability],
) -> Set[Capability]:
    """
    Upgrade capabilities using human role flags.

    Tier3 + flags is where "Juror / Node Operator / Validator / Emissary"
    bundle kicks in (and creator rewards eligibility starts, since posting is Tier3).
    """
    caps: Set[Capability] = set(base_caps)

    # Creator rewards eligibility begins at Tier3 (because Tier3 is when posting begins).
    if tier >= PoHTier.TIER3 and flags.wants_creator:
        caps.add(Capability.EARN_CREATOR_REWARDS)

    # Juror: only meaningful at Tier3.
    if tier >= PoHTier.TIER3 and flags.wants_juror:
        caps.add(Capability.SERVE_AS_JUROR)

    # Node operator / gateway / validator: Tier3 per spec.
    if tier >= PoHTier.TIER3 and flags.wants_operator:
        caps.add(Capability.RUN_NODE)
        caps.add(Capability.OPERATE_GATEWAY)
        caps.add(Capability.OPERATE_COMMUNITY_NODE)

    if tier >= PoHTier.TIER3 and flags.wants_validator:
        caps.add(Capability.RUN_VALIDATOR)

    # Emissary / delegate: Tier3 + explicit opt-in.
    if tier >= PoHTier.TIER3 and flags.wants_emissary:
        caps.add(Capability.ACT_AS_EMISSARY)

    return caps


def compute_effective_role_profile(
    poh_tier: int,
    flags: Optional[HumanRoleFlags] = None,
) -> EffectiveRoleProfile:
    """
    Main entry point for API/selector code.

    Given:
        - an integer PoH tier from the ledger
        - optional HumanRoleFlags (from the ledger)

    return a fully computed EffectiveRoleProfile.
    """
    tier_enum: PoHTier = PoHTier(max(0, min(int(poh_tier), int(PoHTier.TIER3))))
    if flags is None:
        flags = HumanRoleFlags()

    base_caps = _TIER_BASE_CAPS[tier_enum]
    caps = _apply_flags_to_caps(tier_enum, flags, base_caps)

    return EffectiveRoleProfile(
        poh_tier=tier_enum,
        flags=flags,
        capabilities=caps,
    )


# ============================================================
# Topology helpers
# ============================================================

@dataclass(frozen=True)
class NodeTopologyProfile:
    """
    What a *node* is allowed / expected to do based on its kind.

    This is independent from human PoH roles. A single person might
    control multiple nodes; a node might serve many humans.
    """
    kind: NodeKind
    exposes_public_api: bool
    participates_in_consensus: bool
    stores_group_data: bool
    is_private_scope: bool


_NODE_KIND_PROFILES: Dict[NodeKind, NodeTopologyProfile] = {
    NodeKind.OBSERVER_CLIENT: NodeTopologyProfile(
        kind=NodeKind.OBSERVER_CLIENT,
        exposes_public_api=False,
        participates_in_consensus=False,
        stores_group_data=False,
        is_private_scope=False,
    ),
    NodeKind.PUBLIC_GATEWAY: NodeTopologyProfile(
        kind=NodeKind.PUBLIC_GATEWAY,
        exposes_public_api=True,
        participates_in_consensus=False,
        stores_group_data=True,
        is_private_scope=False,
    ),
    NodeKind.VALIDATOR_NODE: NodeTopologyProfile(
        kind=NodeKind.VALIDATOR_NODE,
        exposes_public_api=True,
        participates_in_consensus=True,
        stores_group_data=True,
        is_private_scope=False,
    ),
    NodeKind.COMMUNITY_NODE: NodeTopologyProfile(
        kind=NodeKind.COMMUNITY_NODE,
        exposes_public_api=True,
        participates_in_consensus=False,  # can be toggled via config later
        stores_group_data=True,
        is_private_scope=True,
    ),
}


def node_topology_profile(kind: NodeKind) -> NodeTopologyProfile:
    """
    Return a descriptive topology profile for a node kind.

    Useful for:
        - `/roles/topology` API responses
        - configuration UIs
        - internal checks (e.g., "validators must be VALIDATOR_NODE").
    """
    return _NODE_KIND_PROFILES[kind]


# ============================================================
# Introspection helpers for UI / docs
# ============================================================

def capability_matrix_by_tier() -> Dict[str, List[str]]:
    """
    Return a JSON-friendly representation of the tier → capabilities
    mapping that the frontend can render as a table.
    """
    out: Dict[str, List[str]] = {}
    for tier, caps in _TIER_BASE_CAPS.items():
        out[str(int(tier))] = sorted(c.value for c in caps)
    return out


def capability_matrix_full_example() -> Dict[str, Dict[str, List[str]]]:
    """
    Example of how capabilities change with flags, suitable for
    documentation or a `/roles/meta` endpoint.

    Keys:
        tier: "0".."3"
        scenario: "default", "juror", "validator", "emissary", "operator+validator"
    """
    scenarios = {
        "default": HumanRoleFlags(),
        "juror": HumanRoleFlags(wants_juror=True),
        "validator": HumanRoleFlags(wants_validator=True),
        "emissary": HumanRoleFlags(wants_emissary=True),
        "operator+validator": HumanRoleFlags(wants_operator=True, wants_validator=True),
    }

    result: Dict[str, Dict[str, List[str]]] = {}
    for tier in PoHTier:
        tier_key = str(int(tier))
        result[tier_key] = {}
        for name, flags in scenarios.items():
            profile = compute_effective_role_profile(tier, flags)
            result[tier_key][name] = sorted(c.value for c in profile.capabilities)

    return result
