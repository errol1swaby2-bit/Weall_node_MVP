"""
weall_node/api/groups.py
============================================================

Full Scope v2-oriented Groups module with:

- Group creation + membership
- Emissary election (STV-style ranked ballots) scaffolding
- Group multisig configuration (signers + threshold)
- BOTH legacy endpoints (used by older frontend scripts) and REST-ish endpoints
- Fixes:
  - /groups/list shadowing by /groups/{group_id} (order of route declarations)
  - POST /groups/create 422 "created_by required" (created_by optional; default from header)

Ledger layout:
  executor.ledger["groups"]["groups"][group_id] = group_dict

Group dict schema (stable keys):
  id, name, description, tags, visibility, created_by, created_at, status
  members: [account_id, ...]
  emissaries: [account_id, ...]
  multisig: {signers: [...], threshold: int, updated_at, updated_by}
  emissary_election: {seats, min_members, candidates, ballots, last_results, updated_at}

Auth model:
  - MVP uses "X-WeAll-User" header
  - Capability checks are best-effort:
      if executor.roles.effective_profile exists, we can enforce.
      otherwise, we allow (bootstrap/dev friendliness).

NOTE: Treasury enforcement happens in treasury.py, but it depends on group.emissaries
      and group.multisig being present here.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/groups", tags=["groups"])

# Spec defaults
DEFAULT_EMISSARY_SEATS = 5
MIN_MEMBERS_FOR_EMISSARIES = 15

# STV math precision
getcontext().prec = 28


# ---------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------

def _now_ts() -> int:
    return int(time.time())


def _user_id_from_header(request: Request) -> str:
    uid = (request.headers.get("X-WeAll-User") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Missing X-WeAll-User header")
    return uid


def _ledger() -> Dict[str, Any]:
    led = getattr(executor, "ledger", None)
    if led is None:
        raise HTTPException(status_code=500, detail="ledger_not_initialized")
    return led


def _groups_root() -> Dict[str, Any]:
    root = _ledger().setdefault("groups", {})
    if not isinstance(root, dict):
        _ledger()["groups"] = {}
        root = _ledger()["groups"]
    root.setdefault("groups", {})
    if not isinstance(root["groups"], dict):
        root["groups"] = {}
    return root


def _groups() -> Dict[str, Dict[str, Any]]:
    return _groups_root()["groups"]


def _get_group(group_id: str) -> Dict[str, Any]:
    g = _groups().get(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="group_not_found")
    if not isinstance(g, dict):
        raise HTTPException(status_code=500, detail="group_corrupt")
    return g


def _ensure_list(group: Dict[str, Any], key: str) -> List[Any]:
    v = group.setdefault(key, [])
    if not isinstance(v, list):
        group[key] = []
    return group[key]


def _normalize_account(x: str) -> str:
    return (x or "").strip()


def _best_effort_capability(user_id: str, capability: str) -> bool:
    """
    If executor.roles.effective_profile exists, enforce capability membership.
    Otherwise return True (bootstrap/dev-friendly).
    """
    roles = getattr(executor, "roles", None)
    if roles is None or not hasattr(roles, "effective_profile"):
        return True
    try:
        prof = roles.effective_profile(user_id)
        caps = getattr(prof, "capabilities", None) or set()
        # caps may be enums or strings; compare by value if possible
        for c in caps:
            if getattr(c, "value", c) == capability:
                return True
        return False
    except Exception:
        # if the capability system isn't ready, don't block dev
        return True


def _require_cap(user_id: str, capability: str) -> None:
    if not _best_effort_capability(user_id, capability):
        raise HTTPException(status_code=403, detail=f"missing_capability:{capability}")


def _init_group_record(
    *,
    name: str,
    description: str,
    tags: List[str],
    visibility: str,
    created_by: str,
) -> Dict[str, Any]:
    gid = secrets.token_hex(8)
    now = _now_ts()
    return {
        "id": gid,
        "name": name,
        "description": description or "",
        "tags": list(tags or []),
        "visibility": visibility or "public",
        "created_by": created_by,
        "created_at": now,
        "status": "active",
        "members": [created_by],
        "emissaries": [],
        "multisig": {"signers": [], "threshold": 0, "updated_at": now, "updated_by": created_by},
        "emissary_election": {
            "seats": DEFAULT_EMISSARY_SEATS,
            "min_members": MIN_MEMBERS_FOR_EMISSARIES,
            "candidates": [],
            "ballots": {},        # voter_id -> [candidate_id,...]
            "last_results": None,
            "updated_at": now,
        },
    }


# ---------------------------------------------------------------------
# STV (ranked-choice multiwinner) - deterministic MVP
# ---------------------------------------------------------------------

@dataclass
class STVResult:
    seats: int
    quota: Decimal
    elected: List[str]
    eliminated: List[str]
    rounds: List[Dict[str, Any]]


def _stv_compute(candidates: List[str], ballots: List[List[str]], seats: int) -> STVResult:
    """
    Simple multi-winner STV using Droop quota and elimination.
    Includes fractional transfer for surplus (Gregory method-ish).
    Deterministic and good enough for MVP.
    """
    seats = max(1, int(seats or 1))

    # normalize candidates
    cand = []
    seen = set()
    for c in (candidates or []):
        c = _normalize_account(c)
        if c and c not in seen:
            cand.append(c)
            seen.add(c)
    cand.sort()
    cand_set = set(cand)

    # clean ballots
    clean_ballots: List[List[str]] = []
    for b in ballots or []:
        out: List[str] = []
        seen_b = set()
        for c in b or []:
            c = _normalize_account(c)
            if c in cand_set and c not in seen_b:
                out.append(c)
                seen_b.add(c)
        if out:
            clean_ballots.append(out)

    total_votes = Decimal(len(clean_ballots))
    if not cand or total_votes <= 0:
        return STVResult(seats=seats, quota=Decimal(0), elected=[], eliminated=[], rounds=[])

    quota = (total_votes // Decimal(seats + 1)) + Decimal(1)

    active: Set[str] = set(cand)
    elected: List[str] = []
    eliminated: List[str] = []
    rounds: List[Dict[str, Any]] = []

    weights: List[Decimal] = [Decimal(1) for _ in clean_ballots]

    def first_active(ballot: List[str], active_set: Set[str]) -> Optional[str]:
        for p in ballot:
            if p in active_set:
                return p
        return None

    assignment: List[Optional[str]] = [first_active(b, active) for b in clean_ballots]

    safety = 0
    while len(elected) < seats and active:
        safety += 1
        if safety > 5000:
            break

        tally: Dict[str, Decimal] = {c: Decimal(0) for c in active}
        for a, w in zip(assignment, weights):
            if a and a in active:
                tally[a] += w

        round_info: Dict[str, Any] = {
            "active": sorted(active),
            "quota": str(quota),
            "tally": {k: str(v) for k, v in sorted(tally.items())},
            "elected_this_round": [],
            "eliminated_this_round": [],
        }

        winners = [c for c in sorted(active) if tally.get(c, Decimal(0)) >= quota]
        if winners:
            for w in winners:
                if w not in active:
                    continue
                elected.append(w)
                active.remove(w)
                round_info["elected_this_round"].append(w)

                total_for_w = tally.get(w, Decimal(0))
                surplus = total_for_w - quota
                if surplus <= 0 or total_for_w <= 0:
                    # just reassign ballots that were on winner
                    for i, a in enumerate(assignment):
                        if a == w:
                            assignment[i] = first_active(clean_ballots[i], active)
                    continue

                transfer_factor = surplus / total_for_w

                # split weights: keep (1 - tf) with winner, send tf to next active
                for i, a in enumerate(assignment):
                    if a != w:
                        continue
                    transfer_amt = weights[i] * transfer_factor
                    weights[i] = weights[i] - transfer_amt

                    nxt = first_active(clean_ballots[i], active)
                    if nxt and transfer_amt > 0:
                        clean_ballots.append(list(clean_ballots[i]))
                        weights.append(transfer_amt)
                        assignment.append(nxt)

                # remove all remaining winner assignments (winner is no longer active)
                for i, a in enumerate(assignment):
                    if a == w:
                        assignment[i] = None

            rounds.append(round_info)
            continue

        # eliminate lowest
        lowest = min(active, key=lambda c: (tally.get(c, Decimal(0)), c))
        active.remove(lowest)
        eliminated.append(lowest)
        round_info["eliminated_this_round"].append(lowest)

        for i, a in enumerate(assignment):
            if a == lowest:
                assignment[i] = first_active(clean_ballots[i], active)

        rounds.append(round_info)

        # if remaining candidates fit remaining seats, elect all
        remaining = seats - len(elected)
        if remaining > 0 and len(active) <= remaining:
            for c in sorted(active):
                elected.append(c)
            active.clear()

    return STVResult(seats=seats, quota=quota, elected=elected[:seats], eliminated=eliminated, rounds=rounds)


def _compute_emissary_projection(group: Dict[str, Any]) -> Dict[str, Any]:
    election = group.setdefault("emissary_election", {})
    seats = int(election.get("seats") or DEFAULT_EMISSARY_SEATS)
    candidates = list(election.get("candidates") or [])
    ballots_map = dict(election.get("ballots") or {})
    ballots = [list(v or []) for v in ballots_map.values()]

    res = _stv_compute(candidates=candidates, ballots=ballots, seats=seats)
    projection = {
        "seats": res.seats,
        "quota": str(res.quota),
        "projected_winners": list(res.elected),
        "eliminated": list(res.eliminated),
        "rounds_tail": res.rounds[-3:],
    }
    election["last_results"] = projection
    election["updated_at"] = _now_ts()
    return projection


def _maybe_finalize_emissaries(group: Dict[str, Any]) -> Optional[List[str]]:
    election = group.get("emissary_election") or {}
    min_members = int(election.get("min_members") or MIN_MEMBERS_FOR_EMISSARIES)
    members = group.get("members") or []
    if len(members) < min_members:
        return None

    projection = _compute_emissary_projection(group)
    winners = projection.get("projected_winners") or []
    if not winners:
        return None

    group["emissaries"] = list(winners)

    # If multisig not configured, bootstrap it to emissaries with threshold min(3, len)
    ms = group.setdefault("multisig", {})
    signers = ms.get("signers") or []
    if not signers:
        ms["signers"] = list(winners)
        ms["threshold"] = min(3, len(winners)) if len(winners) >= 1 else 0
        ms["updated_at"] = _now_ts()
        ms["updated_by"] = "system:auto"
        group["multisig"] = ms

    return list(winners)


# ---------------------------------------------------------------------
# Models (legacy endpoints + REST endpoints)
# ---------------------------------------------------------------------

class LegacyCreateGroupBody(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=4000)
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field("public")
    created_by: Optional[str] = None  # IMPORTANT: optional (defaults from header)


class LegacyGetGroupBody(BaseModel):
    group_id: str


class LegacyJoinLeaveBody(BaseModel):
    group_id: str
    account_id: str


class EmissaryStatusBody(BaseModel):
    group_id: str


class EmissaryNominateBody(BaseModel):
    group_id: str
    nominator_id: str
    candidate_id: str


class EmissaryBallotBody(BaseModel):
    group_id: str
    voter_id: str
    ranking: List[str]


class MultisigSetBody(BaseModel):
    group_id: str
    signers: List[str]
    threshold: int


class RestCreateGroupBody(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=4000)
    tags: List[str] = Field(default_factory=list)
    visibility: str = Field("public")


# ---------------------------------------------------------------------
# ROUTE ORDER MATTERS:
# Define explicit subpaths FIRST to prevent /{group_id} shadowing.
# ---------------------------------------------------------------------

@router.get("/list")
def list_groups_get() -> Dict[str, Any]:
    return {"ok": True, "groups": list(_groups().values())}


@router.post("/list")
def list_groups_post() -> Dict[str, Any]:
    return {"ok": True, "groups": list(_groups().values())}


@router.post("/create")
def create_group_legacy(body: LegacyCreateGroupBody, request: Request) -> Dict[str, Any]:
    creator = _normalize_account(body.created_by or "") or _user_id_from_header(request)
    _require_cap(creator, "CREATE_GROUP")

    group = _init_group_record(
        name=body.name,
        description=body.description,
        tags=body.tags,
        visibility=body.visibility,
        created_by=creator,
    )
    _groups()[group["id"]] = group
    return {"ok": True, "group": group}


@router.post("/get")
def get_group_legacy(body: LegacyGetGroupBody) -> Dict[str, Any]:
    group = _get_group(body.group_id)
    return {"ok": True, "group": group}


@router.post("/join")
def join_group_legacy(body: LegacyJoinLeaveBody) -> Dict[str, Any]:
    acct = _normalize_account(body.account_id)
    if not acct:
        raise HTTPException(status_code=400, detail="account_id_required")
    _require_cap(acct, "JOIN_GROUPS")

    group = _get_group(body.group_id)
    members = _ensure_list(group, "members")
    if acct not in members:
        members.append(acct)

    return {"ok": True, "group_id": group["id"], "members": members, "emissaries": group.get("emissaries", [])}


@router.post("/leave")
def leave_group_legacy(body: LegacyJoinLeaveBody) -> Dict[str, Any]:
    acct = _normalize_account(body.account_id)
    if not acct:
        raise HTTPException(status_code=400, detail="account_id_required")
    _require_cap(acct, "LEAVE_GROUPS")

    group = _get_group(body.group_id)
    members = _ensure_list(group, "members")
    emissaries = _ensure_list(group, "emissaries")

    if acct in members:
        members.remove(acct)
    if acct in emissaries:
        emissaries.remove(acct)

    ms = group.get("multisig") or {}
    signers = ms.get("signers") or []
    if acct in signers:
        signers.remove(acct)
        ms["signers"] = signers
        ms["updated_at"] = _now_ts()
        ms["updated_by"] = acct
        group["multisig"] = ms

    return {"ok": True, "group_id": group["id"], "members": members, "emissaries": emissaries}


@router.post("/emissaries/status")
def emissary_status(body: EmissaryStatusBody) -> Dict[str, Any]:
    group = _get_group(body.group_id)
    election = group.setdefault("emissary_election", {})
    seats = int(election.get("seats") or DEFAULT_EMISSARY_SEATS)
    min_members = int(election.get("min_members") or MIN_MEMBERS_FOR_EMISSARIES)

    members = group.get("members") or []
    candidates = list(election.get("candidates") or [])
    ballots = dict(election.get("ballots") or {})

    projection = _compute_emissary_projection(group)
    finalized = _maybe_finalize_emissaries(group)
    if finalized is not None:
        _groups()[group["id"]] = group

    return {
        "ok": True,
        "group_id": group["id"],
        "member_count": len(members),
        "min_members": min_members,
        "seats": seats,
        "members": members,
        "candidates": candidates,
        "ballots_count": len(ballots),
        "current_emissaries": group.get("emissaries", []),
        "projection": projection,
        "auto_finalized": finalized,
    }


@router.post("/emissaries/nominate")
def emissary_nominate(body: EmissaryNominateBody) -> Dict[str, Any]:
    group = _get_group(body.group_id)

    nom = _normalize_account(body.nominator_id)
    cand = _normalize_account(body.candidate_id)
    if not nom or not cand:
        raise HTTPException(status_code=400, detail="nominator_id_and_candidate_id_required")

    members = group.get("members") or []
    if nom not in members:
        raise HTTPException(status_code=403, detail="nominator_must_be_member")
    if cand not in members:
        raise HTTPException(status_code=403, detail="candidate_must_be_member")

    election = group.setdefault("emissary_election", {})
    min_members = int(election.get("min_members") or MIN_MEMBERS_FOR_EMISSARIES)
    if len(members) < min_members:
        raise HTTPException(status_code=400, detail=f"requires_{min_members}_members_for_emissary_election")

    candidates = election.setdefault("candidates", [])
    if cand not in candidates:
        candidates.append(cand)
        candidates.sort()
    election["updated_at"] = _now_ts()

    _groups()[group["id"]] = group
    return {"ok": True, "group_id": group["id"], "candidates": candidates}


@router.post("/emissaries/ballot")
def emissary_ballot(body: EmissaryBallotBody) -> Dict[str, Any]:
    group = _get_group(body.group_id)

    voter = _normalize_account(body.voter_id)
    if not voter:
        raise HTTPException(status_code=400, detail="voter_id_required")

    members = group.get("members") or []
    if voter not in members:
        raise HTTPException(status_code=403, detail="voter_must_be_member")

    election = group.setdefault("emissary_election", {})
    candidates = list(election.get("candidates") or [])
    if not candidates:
        raise HTTPException(status_code=400, detail="no_candidates_nominated")

    # normalize ranking to valid candidates
    seen: Set[str] = set()
    ranking: List[str] = []
    for c in body.ranking or []:
        c = _normalize_account(c)
        if c in candidates and c not in seen:
            ranking.append(c)
            seen.add(c)
    if not ranking:
        raise HTTPException(status_code=400, detail="ranking_required")

    ballots = election.setdefault("ballots", {})
    ballots[voter] = ranking
    election["updated_at"] = _now_ts()

    projection = _compute_emissary_projection(group)
    finalized = _maybe_finalize_emissaries(group)

    _groups()[group["id"]] = group
    return {"ok": True, "group_id": group["id"], "ballots_count": len(ballots), "projection": projection, "auto_finalized": finalized}


@router.post("/multisig/set")
def multisig_set(body: MultisigSetBody, request: Request) -> Dict[str, Any]:
    group = _get_group(body.group_id)
    caller = _user_id_from_header(request)

    # rule: emissaries can set multisig; if no emissaries yet, creator can set for bootstrap
    emissaries = set(group.get("emissaries") or [])
    if emissaries:
        if caller not in emissaries:
            raise HTTPException(status_code=403, detail="only_emissaries_can_set_multisig")
    else:
        if caller != group.get("created_by"):
            raise HTTPException(status_code=403, detail="only_creator_can_set_multisig_until_emissaries_exist")

    # normalize signers (unique + order)
    signers: List[str] = []
    for s in body.signers or []:
        s = _normalize_account(s)
        if s and s not in signers:
            signers.append(s)

    threshold = int(body.threshold or 0)
    if threshold < 0:
        threshold = 0
    if threshold > len(signers):
        raise HTTPException(status_code=400, detail="threshold_exceeds_signers")

    # if emissaries exist, require signers be emissaries
    if emissaries:
        bad = [s for s in signers if s not in emissaries]
        if bad:
            raise HTTPException(status_code=400, detail=f"signers_must_be_emissaries:{','.join(bad)}")

    group["multisig"] = {
        "signers": signers,
        "threshold": threshold,
        "updated_at": _now_ts(),
        "updated_by": caller,
    }
    _groups()[group["id"]] = group
    return {"ok": True, "group_id": group["id"], "multisig": group["multisig"]}


# ---------------------------------------------------------------------
# REST-ish endpoints (your OpenAPI lists /groups and /groups/{group_id})
# ---------------------------------------------------------------------

@router.get("")
def list_groups_rest() -> Dict[str, Any]:
    return {"ok": True, "groups": list(_groups().values())}


@router.post("")
def create_group_rest(body: RestCreateGroupBody, request: Request) -> Dict[str, Any]:
    creator = _user_id_from_header(request)
    _require_cap(creator, "CREATE_GROUP")

    group = _init_group_record(
        name=body.name,
        description=body.description,
        tags=body.tags,
        visibility=body.visibility,
        created_by=creator,
    )
    _groups()[group["id"]] = group
    return {"ok": True, "group": group}


@router.get("/{group_id}")
def get_group_rest(group_id: str) -> Dict[str, Any]:
    group = _get_group(group_id)
    return {"ok": True, "group": group}


@router.post("/{group_id}/join")
def join_group_rest(group_id: str, request: Request) -> Dict[str, Any]:
    acct = _user_id_from_header(request)
    _require_cap(acct, "JOIN_GROUPS")

    group = _get_group(group_id)
    members = _ensure_list(group, "members")
    if acct not in members:
        members.append(acct)

    return {"ok": True, "group_id": group["id"], "members": members, "emissaries": group.get("emissaries", [])}


@router.post("/{group_id}/leave")
def leave_group_rest(group_id: str, request: Request) -> Dict[str, Any]:
    acct = _user_id_from_header(request)
    _require_cap(acct, "LEAVE_GROUPS")

    group = _get_group(group_id)
    members = _ensure_list(group, "members")
    emissaries = _ensure_list(group, "emissaries")

    if acct in members:
        members.remove(acct)
    if acct in emissaries:
        emissaries.remove(acct)

    return {"ok": True, "group_id": group["id"], "members": members, "emissaries": emissaries}
