from __future__ import annotations

"""
weall_node/api/groups.py
--------------------------------------------------
Minimal Groups & Emissaries API for WeAll.

This module creates a lightweight group/DAO layer that can be used
by the frontend and governance layer.

Design goals (MVP):

- Groups have:
    - id, slug, name, charter, scope, created_by
    - members (user ids / handles)
    - emissaries (subset of members)
    - settings with emissary constraints

- Membership is PoH-gated at Tier 2+ (create/join).
- Emissaries require that:
    - the group has at least `min_members_for_emissaries` members
    - the emissary set has length between min_emissaries & max_emissaries
    - all emissaries are members of the group

Ledger layout:

executor.ledger["groups"] = {
    "groups": {
        "<group_id>": {
            "id": str,
            "slug": str,
            "name": str,
            "charter": str,
            "scope": str,
            "created_by": str,
            "created_at": int,
            "updated_at": int,
            "members": [str, ...],
            "emissaries": [str, ...],
            "settings": {
                "min_members_for_emissaries": int,
                "min_emissaries": int,
                "max_emissaries": int,
            },
        },
        ...
    },
    "by_member": {
        "<user_id>": ["<group_id>", ...],
        ...
    },
}
"""

import re
import time
import secrets
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..weall_executor import executor
from .verification import require_poh_level

router = APIRouter(prefix="/groups", tags=["groups"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ns() -> Dict[str, Any]:
    """
    Ensure the groups namespace exists in the ledger.
    """
    led = executor.ledger
    root = led.setdefault("groups", {})
    root.setdefault("groups", {})
    root.setdefault("by_member", {})
    return root


def _groups_map() -> Dict[str, Dict[str, Any]]:
    return _ns().setdefault("groups", {})


def _by_member() -> Dict[str, List[str]]:
    ns = _ns()
    bm = ns.get("by_member")
    if not isinstance(bm, dict):
        bm = {}
        ns["by_member"] = bm
    return bm  # type: ignore[return-value]


def _save():
    try:
        executor.save_state()
    except Exception:
        pass


def _slugify(name: str) -> str:
    """
    Very small slug helper; not guaranteed unique by itself.
    """
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "group"


def _ensure_unique_slug(base_slug: str) -> str:
    groups = _groups_map()
    existing = {g.get("slug") for g in groups.values()}
    if base_slug not in existing:
        return base_slug
    i = 2
    while True:
        cand = f"{base_slug}-{i}"
        if cand not in existing:
            return cand
        i += 1


def _update_member_index(group_id: str, members: List[str]) -> None:
    """
    Rebuild the by_member index for a single group.
    """
    bm = _by_member()
    # Remove group_id from all current entries
    for uid, glist in list(bm.items()):
        if group_id in glist:
            glist = [g for g in glist if g != group_id]
            if glist:
                bm[uid] = glist
            else:
                bm.pop(uid, None)

    # Add back based on provided members
    for uid in members:
        uid = str(uid)
        bm.setdefault(uid, [])
        if group_id not in bm[uid]:
            bm[uid].append(group_id)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class GroupSettings(BaseModel):
    min_members_for_emissaries: int = Field(15, ge=1, le=10000)
    min_emissaries: int = Field(5, ge=1, le=1000)
    max_emissaries: int = Field(21, ge=1, le=1000)


class GroupCreate(BaseModel):
    name: str = Field(..., max_length=200)
    slug: Optional[str] = Field(None, max_length=64)
    charter: str = Field(..., max_length=4000)
    scope: Optional[str] = Field(
        "local",
        description="Human-readable scope hint (e.g. 'local', 'thematic').",
        max_length=64,
    )
    created_by: str = Field(..., description="@handle / PoH id for creator")
    settings: Optional[GroupSettings] = None


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    charter: Optional[str] = Field(None, max_length=4000)
    scope: Optional[str] = Field(None, max_length=64)
    settings: Optional[GroupSettings] = None


class GroupPublic(BaseModel):
    id: str
    slug: str
    name: str
    charter: str
    scope: Optional[str]
    created_by: str
    created_at: int
    updated_at: int
    members: List[str]
    emissaries: List[str]
    settings: GroupSettings


class MembershipAction(BaseModel):
    user_id: str = Field(..., description="@handle / PoH id")


class EmissaryElectionRequest(BaseModel):
    requested_by: str = Field(..., description="@handle / PoH id starting the election")
    emissaries: List[str] = Field(..., description="List of member ids to serve as emissaries")


# ---------------------------------------------------------------------------
# Core accessors
# ---------------------------------------------------------------------------


def _get_group(group_id: str) -> Dict[str, Any]:
    gmap = _groups_map()
    rec = gmap.get(group_id)
    if not rec:
        raise HTTPException(status_code=404, detail="group_not_found")
    return rec


def _serialize_group(rec: Dict[str, Any]) -> GroupPublic:
    # normalize settings
    raw_settings = rec.get("settings") or {}
    settings = GroupSettings(**raw_settings)
    return GroupPublic(
        id=str(rec.get("id")),
        slug=str(rec.get("slug")),
        name=str(rec.get("name")),
        charter=str(rec.get("charter")),
        scope=rec.get("scope"),
        created_by=str(rec.get("created_by")),
        created_at=int(rec.get("created_at")),
        updated_at=int(rec.get("updated_at")),
        members=[str(m) for m in rec.get("members") or []],
        emissaries=[str(e) for e in rec.get("emissaries") or []],
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=Dict[str, Any])
def list_groups(member: Optional[str] = None) -> Dict[str, Any]:
    """
    List groups, optionally filtered to a member id.
    """
    gmap = _groups_map()
    if member:
        bm = _by_member()
        ids = set(bm.get(member) or [])
        groups = [_serialize_group(g) for gid, g in gmap.items() if gid in ids]
    else:
        groups = [_serialize_group(g) for g in gmap.values()]

    return {"groups": groups}


@router.post("", response_model=GroupPublic)
def create_group(payload: GroupCreate) -> GroupPublic:
    """
    Create a new group. Requires PoH Tier 2+ for creator.
    """
    # PoH gate: Tier 2 user can create groups.
    require_poh_level(payload.created_by, min_level=2)

    gmap = _groups_map()
    now = int(time.time())

    base_slug = _slugify(payload.slug or payload.name)
    slug = _ensure_unique_slug(base_slug)

    group_id = secrets.token_hex(8)
    settings = (payload.settings or GroupSettings()).dict()

    rec: Dict[str, Any] = {
        "id": group_id,
        "slug": slug,
        "name": payload.name,
        "charter": payload.charter,
        "scope": payload.scope,
        "created_by": payload.created_by,
        "created_at": now,
        "updated_at": now,
        "members": [payload.created_by],
        "emissaries": [],
        "settings": settings,
    }

    gmap[group_id] = rec
    _update_member_index(group_id, rec["members"])
    _save()
    return _serialize_group(rec)


@router.get("/{group_id}", response_model=GroupPublic)
def get_group(group_id: str) -> GroupPublic:
    rec = _get_group(group_id)
    return _serialize_group(rec)


@router.post("/{group_id}/join", response_model=GroupPublic)
def join_group(group_id: str, payload: MembershipAction) -> GroupPublic:
    """
    Join a group. Requires PoH Tier 2+.
    """
    require_poh_level(payload.user_id, min_level=2)
    rec = _get_group(group_id)
    members = rec.setdefault("members", [])
    uid = str(payload.user_id)
    if uid not in members:
        members.append(uid)
        rec["updated_at"] = int(time.time())
        _update_member_index(group_id, members)
        _save()
    return _serialize_group(rec)


@router.post("/{group_id}/leave", response_model=GroupPublic)
def leave_group(group_id: str, payload: MembershipAction) -> GroupPublic:
    """
    Leave a group. Does not allow removing the last remaining member.
    """
    rec = _get_group(group_id)
    members: List[str] = [str(m) for m in rec.get("members") or []]
    uid = str(payload.user_id)

    if uid not in members:
        # idempotent leave
        return _serialize_group(rec)

    if len(members) <= 1:
        raise HTTPException(status_code=400, detail="cannot_remove_last_member")

    members = [m for m in members if m != uid]
    rec["members"] = members

    # Also remove from emissaries if present
    emissaries = [str(e) for e in rec.get("emissaries") or []]
    if uid in emissaries:
        emissaries = [e for e in emissaries if e != uid]
        rec["emissaries"] = emissaries

    rec["updated_at"] = int(time.time())
    _update_member_index(group_id, members)
    _save()
    return _serialize_group(rec)


@router.post("/{group_id}/emissaries/elect", response_model=GroupPublic)
def elect_emissaries(group_id: str, payload: EmissaryElectionRequest) -> GroupPublic:
    """
    Set the emissary set for a group.

    In the full spec this would be driven by an STV election; for the
    MVP we allow a caller to directly set the list, subject to the
    constraints described in GroupSettings.

    Requires:
    - requester has PoH Tier 2+
    - all nominees are members
    - group has at least `min_members_for_emissaries` members
    - number of emissaries is within [min_emissaries, max_emissaries]
    """
    require_poh_level(payload.requested_by, min_level=2)

    rec = _get_group(group_id)
    members = [str(m) for m in rec.get("members") or []]

    if not members:
        raise HTTPException(status_code=400, detail="group_has_no_members")

    settings = GroupSettings(**(rec.get("settings") or {}))

    if len(members) < settings.min_members_for_emissaries:
        raise HTTPException(
            status_code=400,
            detail=f"min_members_for_emissaries={settings.min_members_for_emissaries} not satisfied",
        )

    unique_nominees: List[str] = []
    for uid in payload.emissaries:
        uid = str(uid)
        if uid not in members:
            raise HTTPException(status_code=400, detail=f"nominee_not_member:{uid}")
        if uid not in unique_nominees:
            unique_nominees.append(uid)

    if len(unique_nominees) < settings.min_emissaries:
        raise HTTPException(
            status_code=400,
            detail=f"min_emissaries={settings.min_emissaries} not satisfied",
        )

    if len(unique_nominees) > settings.max_emissaries:
        unique_nominees = unique_nominees[: settings.max_emissaries]

    rec["emissaries"] = unique_nominees
    rec["updated_at"] = int(time.time())
    _save()
    return _serialize_group(rec)


@router.get("/{group_id}/emissaries", response_model=Dict[str, Any])
def get_emissaries(group_id: str) -> Dict[str, Any]:
    rec = _get_group(group_id)
    emissaries = [str(e) for e in rec.get("emissaries") or []]
    return {"group_id": rec.get("id"), "emissaries": emissaries}
