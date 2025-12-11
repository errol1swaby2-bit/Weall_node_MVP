"""
weall_node/api/groups.py
--------------------------------------------------
Groups & emissaries API, wired to network roles.

Implements a thin MVP of the Full Scope group/DAO layer:

    - Groups have:
        * id, slug, name, charter, scope, created_by, created_at
        * members[]
        * emissaries[]

    - Role gating:
        * CREATE_GROUP capability required to create a group
          (Tier 3).
        * JOIN_GROUPS capability required to join.
        * LEAVE_GROUPS capability required to leave.
        * ACT_AS_EMISSARY capability + membership required
          to become an emissary.

STV elections etc. can be layered on top later; this file focuses
on getting the ledger layout and role constraints correct.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..weall_executor import executor
from ..weall_runtime import roles as runtime_roles

router = APIRouter(prefix="/groups", tags=["groups"])


# ============================================================
# Ledger helpers
# ============================================================

def _groups_root() -> Dict[str, Any]:
    return executor.ledger.setdefault("groups", {"groups": {}})


def _groups() -> Dict[str, Dict[str, Any]]:
    root = _groups_root()
    return root.setdefault("groups", {})


def _lookup_poh_record(user_id: str) -> Optional[dict]:
    poh_root = executor.ledger.setdefault("poh", {})
    records = poh_root.setdefault("records", {})
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


def _effective_profile(user_id: str) -> runtime_roles.EffectiveRoleProfile:
    rec = _lookup_poh_record(user_id)
    if not rec:
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

    tier = int(rec.get("tier", 0))
    flags = _extract_flags_from_record(rec)
    return runtime_roles.compute_effective_role_profile(tier, flags)


def _require_profile_with_cap(capability: runtime_roles.Capability):
    """
    Factory: require X-WeAll-User header and a given capability.
    """

    async def dependency(
        x_weall_user: str = Header(
            ...,
            alias="X-WeAll-User",
            description="WeAll user identifier (e.g. '@handle' or wallet id).",
        )
    ) -> str:
        profile = _effective_profile(x_weall_user)
        if capability not in profile.capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required capability: {capability.value}",
            )
        return x_weall_user

    return dependency


# ============================================================
# Models
# ============================================================

class GroupCreate(BaseModel):
    slug: str = Field(..., max_length=64, description="URL-safe slug, unique per group.")
    name: str = Field(..., max_length=200)
    charter: str = Field(
        "",
        max_length=8000,
        description="Plain-text charter / mission statement.",
    )
    scope: str = Field(
        "global",
        description="Optional hint: 'global', 'regional', 'topic', etc.",
    )
    created_by: str = Field(..., description="@handle of the creator")


class Group(BaseModel):
    id: str
    slug: str
    name: str
    charter: str
    scope: str
    created_by: str
    created_at: float
    members: List[str]
    emissaries: List[str]


class GroupsListResponse(BaseModel):
    ok: bool = True
    groups: List[Group]


class GroupSingleResponse(BaseModel):
    ok: bool = True
    group: Group


class JoinLeaveResponse(BaseModel):
    ok: bool = True
    group_id: str
    members: List[str]
    emissaries: List[str]


class EmissaryChangeRequest(BaseModel):
    """
    For now, only supports self-add/self-remove semantics; the
    caller id is taken from X-WeAll-User, not from this payload.
    """
    pass


# ============================================================
# Routes
# ============================================================

@router.get("", response_model=GroupsListResponse)
def list_groups() -> Dict[str, Any]:
    """
    Public listing of groups.
    """
    groups = _groups()
    return {
        "ok": True,
        "groups": [Group(**g) for g in groups.values()],
    }


@router.get("/{group_id}", response_model=GroupSingleResponse)
def get_group(group_id: str) -> Dict[str, Any]:
    groups = _groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"ok": True, "group": Group(**groups[group_id])}


@router.post("", response_model=GroupSingleResponse)
def create_group(
    payload: GroupCreate,
    creator_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.CREATE_GROUP)
    ),
) -> Dict[str, Any]:
    """
    Create a new group.

    Requirements:

        - Caller must have CREATE_GROUP capability (Tier 3).
        - created_by must match X-WeAll-User to prevent spoofing.

    The creator is automatically added as a member, and if they have
    ACT_AS_EMISSARY capability, also as an emissary.
    """
    if payload.created_by != creator_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="created_by must match the authenticated user",
        )

    groups = _groups()

    # Ensure slug uniqueness
    for g in groups.values():
        if g.get("slug") == payload.slug:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slug already in use",
            )

    group_id = secrets.token_hex(8)
    now = time.time()

    profile = _effective_profile(creator_id)
    members = [creator_id]
    emissaries: List[str] = []

    if runtime_roles.Capability.ACT_AS_EMISSARY in profile.capabilities:
        emissaries.append(creator_id)

    group = Group(
        id=group_id,
        slug=payload.slug,
        name=payload.name,
        charter=payload.charter,
        scope=payload.scope,
        created_by=payload.created_by,
        created_at=now,
        members=members,
        emissaries=emissaries,
    ).dict()

    groups[group_id] = group

    return {"ok": True, "group": Group(**group)}


@router.post("/{group_id}/join", response_model=JoinLeaveResponse)
def join_group(
    group_id: str,
    user_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.JOIN_GROUPS)
    ),
) -> Dict[str, Any]:
    """
    Join a group (requires JOIN_GROUPS capability, typically Tier 2+).
    """
    groups = _groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail="Group not found")

    group = groups[group_id]
    members: List[str] = group.setdefault("members", [])
    if user_id not in members:
        members.append(user_id)

    groups[group_id] = group

    return {
        "ok": True,
        "group_id": group_id,
        "members": members,
        "emissaries": group.get("emissaries", []),
    }


@router.post("/{group_id}/leave", response_model=JoinLeaveResponse)
def leave_group(
    group_id: str,
    user_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.LEAVE_GROUPS)
    ),
) -> Dict[str, Any]:
    """
    Leave a group (requires LEAVE_GROUPS capability).

    If the user is also an emissary, they are removed from emissaries
    as well.
    """
    groups = _groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail="Group not found")

    group = groups[group_id]
    members: List[str] = group.setdefault("members", [])
    emissaries: List[str] = group.setdefault("emissaries", [])

    if user_id in members:
        members.remove(user_id)
    if user_id in emissaries:
        emissaries.remove(user_id)

    groups[group_id] = group

    return {
        "ok": True,
        "group_id": group_id,
        "members": members,
        "emissaries": emissaries,
    }


@router.post("/{group_id}/emissaries/add", response_model=GroupSingleResponse)
def add_self_as_emissary(
    group_id: str,
    _payload: EmissaryChangeRequest,
    user_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.ACT_AS_EMISSARY)
    ),
) -> Dict[str, Any]:
    """
    Add the caller as an emissary in the given group.

    Requirements:

        - Caller must have ACT_AS_EMISSARY capability.
        - Caller must already be a member of the group.

    (We treat this as a self-service upgrade; STV elections can later
     wrap this in a stricter flow.)
    """
    groups = _groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail="Group not found")

    group = groups[group_id]
    members: List[str] = group.setdefault("members", [])
    emissaries: List[str] = group.setdefault("emissaries", [])

    if user_id not in members:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be a member to become an emissary",
        )

    if user_id not in emissaries:
        emissaries.append(user_id)

    groups[group_id] = group
    return {"ok": True, "group": Group(**group)}


@router.post("/{group_id}/emissaries/remove", response_model=GroupSingleResponse)
def remove_self_as_emissary(
    group_id: str,
    _payload: EmissaryChangeRequest,
    user_id: str = Depends(
        _require_profile_with_cap(runtime_roles.Capability.ACT_AS_EMISSARY)
    ),
) -> Dict[str, Any]:
    """
    Remove the caller from the emissary list of the given group.

    For now, this only supports self-removal.
    """
    groups = _groups()
    if group_id not in groups:
        raise HTTPException(status_code=404, detail="Group not found")

    group = groups[group_id]
    emissaries: List[str] = group.setdefault("emissaries", [])

    if user_id in emissaries:
        emissaries.remove(user_id)

    groups[group_id] = group
    return {"ok": True, "group": Group(**group)}
