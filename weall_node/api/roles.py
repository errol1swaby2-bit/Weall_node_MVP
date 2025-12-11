"""
weall_node/api/roles.py
--------------------------------------------------
Network roles & topology API.

Implements the public-facing endpoints for Full Scope §2:
    - Roles (Observer, Tier1, Tier2, Tier3, Juror, Node Operator,
      Validator, Emissary, Creator)
    - Topology (gateway nodes, validator nodes, community/private nodes)

These endpoints are *read-only*; they describe how the network is
supposed to behave and reveal each user's effective capabilities.

Other API modules (governance, disputes, validators, etc.) should
*consume* the helper `get_effective_profile_for_user()` to enforce
role gating consistently.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..weall_runtime import roles as runtime_roles

router = APIRouter()


# ============================================================
# Pydantic models
# ============================================================

class RoleMetaTier(BaseModel):
    tier: int = Field(..., description="Numeric PoH tier (0 = observer, 1..3)")
    label: str
    description: str
    base_capabilities: List[str]


class RoleMetaResponse(BaseModel):
    tiers: List[RoleMetaTier]
    capability_matrix_examples: Dict[str, Dict[str, List[str]]]
    notes: str


class EffectiveRoleProfileResponse(BaseModel):
    user_id: str
    poh_tier: int
    flags: Dict[str, bool]
    capabilities: List[str]


class NodeTopologyEntry(BaseModel):
    kind: str
    exposes_public_api: bool
    participates_in_consensus: bool
    stores_group_data: bool
    is_private_scope: bool
    description: str


class NodeTopologyResponse(BaseModel):
    node_kinds: List[NodeTopologyEntry]


# ============================================================
# Internal helpers
# ============================================================

def _lookup_poh_record(user_id: str) -> Optional[dict]:
    """
    Look up the PoH record for a given user_id from the executor ledger.

    This assumes the ledger layout:

        executor.ledger["poh"]["records"][user_id] -> {
            "tier": int,
            "status": str,
            "flags": {...}  # optional role flags
        }

    If your actual layout differs, adjust here; this function is
    intentionally centralized so you only need to fix it once.
    """
    poh_state = executor.ledger.get("poh", {})
    records = poh_state.get("records", {})
    return records.get(user_id)


def _extract_flags_from_record(record: dict) -> runtime_roles.HumanRoleFlags:
    flags = record.get("flags") or {}
    return runtime_roles.HumanRoleFlags(
        wants_juror=bool(flags.get("wants_juror", False)),
        wants_validator=bool(flags.get("wants_validator", False)),
        wants_operator=bool(flags.get("wants_operator", False)),
        wants_emissary=bool(flags.get("wants_emissary", False)),
        wants_creator=bool(flags.get("wants_creator", True)),
    )


def get_effective_profile_for_user(user_id: str) -> runtime_roles.EffectiveRoleProfile:
    """
    Single source of truth for computing a user's effective role profile.

    - Reads PoH tier + role flags from the ledger.
    - Uses runtime_roles.compute_effective_role_profile().
    """
    record = _lookup_poh_record(user_id)
    if not record:
        # Treat as pure observer if not found.
        return runtime_roles.compute_effective_role_profile(
            poh_tier=int(runtime_roles.PoHTier.OBSERVER),
            flags=runtime_roles.HumanRoleFlags(
                wants_creator=False,
                wants_juror=False,
                wants_validator=False,
                wants_operator=False,
                wants_emissary=False,
            ),
        )

    tier = int(record.get("tier", int(runtime_roles.PoHTier.OBSERVER)))
    flags = _extract_flags_from_record(record)
    return runtime_roles.compute_effective_role_profile(tier, flags)


async def _require_user_header(
    x_weall_user: Optional[str] = Header(
        default=None,
        alias="X-WeAll-User",
        description="WeAll user identifier (e.g. '@handle' or wallet id).",
    ),
) -> str:
    if not x_weall_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-WeAll-User header.",
        )
    return x_weall_user


# ============================================================
# Endpoints
# ============================================================

@router.get("/roles/meta", response_model=RoleMetaResponse)
def get_roles_meta() -> RoleMetaResponse:
    """
    Describe the canonical roles & tiers for documentation / UI.

    This is effectively the "spec screenshot" endpoint:
    it returns the tier ladder and example capability matrices.
    """
    tier_caps = runtime_roles.capability_matrix_by_tier()
    examples = runtime_roles.capability_matrix_full_example()

    tiers: List[RoleMetaTier] = [
        RoleMetaTier(
            tier=0,
            label="Observer",
            description="Unverified; can only view public content and start verification flows.",
            base_capabilities=tier_caps.get("0", []),
        ),
        RoleMetaTier(
            tier=1,
            label="Tier 1 User",
            description="Email+auth identity; view-only access (no posting/commenting).",
            base_capabilities=tier_caps.get("1", []),
        ),
        RoleMetaTier(
            tier=2,
            label="Tier 2 User",
            description=(
                "Async-video verified; can post, comment, like, flag violations, "
                "join groups, participate in PoH queueing and open disputes."
            ),
            base_capabilities=tier_caps.get("2", []),
        ),
        RoleMetaTier(
            tier=3,
            label="Tier 3 Juror / Verifier / Node-Operator / Creator",
            description=(
                "Live-verified via video with 3 jurors; can do everything Tier 2 can, "
                "plus create groups, propose governance changes, and—if opted in—serve as "
                "jurors, emissaries, node operators or validators."
            ),
            base_capabilities=tier_caps.get("3", []),
        ),
    ]

    notes = (
        "Capabilities shown here are *base* permissions by PoH tier. "
        "Additional capabilities (juror, validator, node operator, emissary, creator "
        "rewards) are granted when a Tier 3 human explicitly opts into those role "
        "flags and meets any reputation / system health constraints."
    )

    return RoleMetaResponse(
        tiers=tiers,
        capability_matrix_examples=examples,
        notes=notes,
    )


@router.get("/roles/effective/me", response_model=EffectiveRoleProfileResponse)
def get_my_effective_role_profile(
    user_id: str = Depends(_require_user_header),
) -> EffectiveRoleProfileResponse:
    """
    Return the effective role profile for the current user.

    Frontend can use this to:
      - show "Signed in as @handle · PoH Tier 3 (juror, validator, emissary...)"
      - enable/disable UI controls (run validator, join juror pool, etc.)
      - debug access issues ("why can't I open disputes?")
    """
    profile = get_effective_profile_for_user(user_id)
    flags = profile.flags

    return EffectiveRoleProfileResponse(
        user_id=user_id,
        poh_tier=int(profile.poh_tier),
        flags={
            "wants_juror": flags.wants_juror,
            "wants_validator": flags.wants_validator,
            "wants_operator": flags.wants_operator,
            "wants_emissary": flags.wants_emissary,
            "wants_creator": flags.wants_creator,
        },
        capabilities=sorted(cap.value for cap in profile.capabilities),
    )


@router.get("/roles/topology", response_model=NodeTopologyResponse)
def get_topology_meta() -> NodeTopologyResponse:
    """
    Describe the intended node topology (§2.2 Topology):

        - P2P overlay for nodes.
        - Public API gateway nodes.
        - Optional private/community nodes.

    This doesn't return live network state; it's a *design schema*
    that config UIs and docs can show.
    """
    entries: List[NodeTopologyEntry] = []

    descriptions: Dict[runtime_roles.NodeKind, str] = {
        runtime_roles.NodeKind.OBSERVER_CLIENT: (
            "Light clients (browsers, mobile apps) that only talk to gateway nodes. "
            "Do not participate in consensus or store long-term group data."
        ),
        runtime_roles.NodeKind.PUBLIC_GATEWAY: (
            "Public API gateway nodes that expose the HTTP/JSON API, bridge to the "
            "P2P overlay, and serve as ingress for observers and Tier 1 users."
        ),
        runtime_roles.NodeKind.VALIDATOR_NODE: (
            "Full nodes that participate in consensus and finality. Must be operated "
            "by Tier 3 humans with validator and operator flags enabled."
        ),
        runtime_roles.NodeKind.COMMUNITY_NODE: (
            'Private or community-owned nodes that primarily serve a group/DAO or '
            "region. May or may not expose public APIs; can be configured to "
            "participate in consensus as the network matures."
        ),
    }

    for kind in runtime_roles.NodeKind:
        profile = runtime_roles.node_topology_profile(kind)
        entries.append(
            NodeTopologyEntry(
                kind=profile.kind.value,
                exposes_public_api=profile.exposes_public_api,
                participates_in_consensus=profile.participates_in_consensus,
                stores_group_data=profile.stores_group_data,
                is_private_scope=profile.is_private_scope,
                description=descriptions.get(kind, ""),
            )
        )

    return NodeTopologyResponse(node_kinds=entries)
