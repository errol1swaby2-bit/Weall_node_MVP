# weall_node/weall_node/api/roles.py
"""
weall_node/api/roles.py
--------------------------------------------------
Network roles & topology API.

Read-only endpoints (Full Scope §2-style) describing:
- PoH tiers (0..3)
- Effective capabilities based on tier + opt-in flags
- Topology kinds (gateway/validator/community/observer)

This module also provides helpers:
- user_has_capability(user_id, capability)
- require_capability(capability) FastAPI dependency
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..security.current_user import current_user_id_from_cookie_optional
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
    Look up PoH record from executor ledger.

    Expected layout:
        executor.ledger["poh"]["records"][user_id] -> {
            "tier": int,
            "status": str,
            "flags": {...}  # optional role flags
        }
    """
    poh_state = executor.ledger.get("poh", {})
    if not isinstance(poh_state, dict):
        return None
    records = poh_state.get("records", {})
    if not isinstance(records, dict):
        return None
    return records.get(user_id)


def _extract_flags_from_record(record: dict) -> runtime_roles.HumanRoleFlags:
    flags = record.get("flags") or {}
    if not isinstance(flags, dict):
        flags = {}
    return runtime_roles.HumanRoleFlags(
        wants_juror=bool(flags.get("wants_juror", False)),
        wants_validator=bool(flags.get("wants_validator", False)),
        wants_operator=bool(flags.get("wants_operator", False)),
        wants_emissary=bool(flags.get("wants_emissary", False)),
        wants_creator=bool(flags.get("wants_creator", True)),
    )


def get_effective_profile_for_user(user_id: str) -> runtime_roles.RoleProfile:
    """
    Canonical effective role profile computation:
    - Reads PoH tier + role flags from ledger
    - Uses runtime_roles.compute_effective_role_profile()
    """
    record = _lookup_poh_record(user_id)
    if not record:
        # Treat as pure observer if not found
        return runtime_roles.compute_effective_role_profile(
            poh_tier=int(runtime_roles.PoHTier.TIER0),
            flags=runtime_roles.HumanRoleFlags(
                wants_creator=False,
                wants_juror=False,
                wants_validator=False,
                wants_operator=False,
                wants_emissary=False,
            ),
        )

    tier = int(record.get("tier", int(runtime_roles.PoHTier.TIER0)))
    flags = _extract_flags_from_record(record)
    return runtime_roles.compute_effective_role_profile(tier, flags)


# ------------------------------------------------------------
# Canonical capability helpers
# ------------------------------------------------------------

def user_has_capability(
    user_id: str,
    capability: runtime_roles.Capability,
) -> bool:
    profile = get_effective_profile_for_user(user_id)
    return capability in profile.capabilities


def require_capability(capability: runtime_roles.Capability):
    """
    FastAPI dependency enforcing a capability based on cookie session
    (preferred) or dev-only X-WeAll-User header fallback.
    """

    async def dependency(
        session_user_id: Optional[str] = Depends(current_user_id_from_cookie_optional),
        x_weall_user: Optional[str] = Header(
            default=None,
            alias="X-WeAll-User",
            description="Legacy identity header (dev-only). Prefer cookie session.",
        ),
    ) -> str:
        user_id = session_user_id or x_weall_user
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
            )

        profile = get_effective_profile_for_user(user_id)
        if capability not in profile.capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing capability: {capability.value}",
            )
        return user_id

    return dependency


# ============================================================
# Public endpoints
# ============================================================

@router.get("/roles/meta", response_model=RoleMetaResponse)
def roles_meta() -> RoleMetaResponse:
    tiers: List[RoleMetaTier] = [
        RoleMetaTier(
            tier=0,
            label="Tier 0 — Observer",
            description="View-only. No interactions.",
            base_capabilities=sorted([c.value for c in runtime_roles.compute_effective_role_profile(0).capabilities]),
        ),
        RoleMetaTier(
            tier=1,
            label="Tier 1 — Verified Human",
            description="Can view + like/comment (where permitted by scope).",
            base_capabilities=sorted([c.value for c in runtime_roles.compute_effective_role_profile(1).capabilities]),
        ),
        RoleMetaTier(
            tier=2,
            label="Tier 2 — Social Actor",
            description="Can post, vote, and join groups.",
            base_capabilities=sorted([c.value for c in runtime_roles.compute_effective_role_profile(2).capabilities]),
        ),
        RoleMetaTier(
            tier=3,
            label="Tier 3 — Steward",
            description="Tier2+, plus eligibility for juror/operator/validator/emissary via opt-in flags.",
            base_capabilities=sorted([c.value for c in runtime_roles.compute_effective_role_profile(3).capabilities]),
        ),
    ]

    return RoleMetaResponse(
        tiers=tiers,
        capability_matrix_examples=runtime_roles.capability_matrix_full_example(),
        notes="Effective capabilities are tier + opt-in flags. Tier3 does not auto-grant work roles without flags.",
    )


@router.get("/roles/me", response_model=EffectiveRoleProfileResponse)
def roles_me(
    session_user_id: Optional[str] = Depends(current_user_id_from_cookie_optional),
    x_weall_user: Optional[str] = Header(default=None, alias="X-WeAll-User"),
) -> EffectiveRoleProfileResponse:
    user_id = session_user_id or x_weall_user
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    record = _lookup_poh_record(user_id) or {}
    tier = int(record.get("tier", 0))
    flags = _extract_flags_from_record(record).to_dict() if record else {
        "wants_creator": False,
        "wants_juror": False,
        "wants_validator": False,
        "wants_operator": False,
        "wants_emissary": False,
    }

    prof = get_effective_profile_for_user(user_id)
    return EffectiveRoleProfileResponse(
        user_id=user_id,
        poh_tier=tier,
        flags=flags,
        capabilities=sorted([c.value for c in prof.capabilities]),
    )


@router.get("/topology", response_model=NodeTopologyResponse)
def topology() -> NodeTopologyResponse:
    kinds = [
        ("observer_client", "Private view-only client."),
        ("public_gateway", "Public API gateway; does not validate."),
        ("validator_node", "Consensus validator node."),
        ("community_node", "Stores group data; serves API; can participate in network services."),
    ]

    node_kinds: List[NodeTopologyEntry] = []
    for kind_str, desc in kinds:
        kind = runtime_roles.NodeKind(kind_str)
        prof = runtime_roles.node_topology_profile(kind)
        node_kinds.append(
            NodeTopologyEntry(
                kind=kind.value,
                exposes_public_api=prof.exposes_public_api,
                participates_in_consensus=prof.participates_in_consensus,
                stores_group_data=prof.stores_group_data,
                is_private_scope=prof.is_private_scope,
                description=desc,
            )
        )

    return NodeTopologyResponse(node_kinds=node_kinds)
