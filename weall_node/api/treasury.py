"""
weall_node/api/treasury.py
---------------------------------
Treasury endpoints for WeAll Node.

Includes:
- GET  /treasury/meta
- GET  /treasury/pools

Spec-v2 oriented:
- Group-controlled spend proposals (multisig by emissaries):
    POST /treasury/group_spend/propose
    POST /treasury/group_spend/sign
    POST /treasury/group_spend/execute
    GET  /treasury/group_spend/list

Notes:
- Spending moves funds out of @weall_treasury to a target account.
- This is NOT minting; total_issued must NOT change.
- WeCoinLedger currently lacks a public transfer() method, so we adjust balances
  directly on the runtime balances map with safety checks.
- Multisig enforcement uses group["multisig"] if set; otherwise:
    - if emissaries exist: signers = emissaries, threshold = min(3, len(signers))
    - else: (bootstrap/dev) signer = created_by, threshold = 1
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter(prefix="/treasury", tags=["treasury"])

TREASURY_ACCOUNT = "@weall_treasury"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_ts() -> float:
    return float(time.time())


def _core():
    # tolerate both executor facade and direct core
    return getattr(executor, "exec", executor)


def _ledger() -> Dict[str, Any]:
    core = _core()
    led = getattr(core, "ledger", None)
    if led is None:
        raise HTTPException(status_code=500, detail="ledger_not_initialized")
    return led


def _wecoin():
    # WeCoin runtime lives on the executor in this repo
    return getattr(executor, "wecoin", None)


def _pool_split_bps(split: Dict[str, float]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for name, frac in (split or {}).items():
        try:
            bps = int(round(float(frac) * 10_000))
        except Exception:
            bps = 0
        out[str(name)] = bps
    return out


def _current_block_reward(wec) -> float:
    if wec is None:
        return 0.0
    chain = _ledger().get("chain") or []
    height = len(chain)
    try:
        if hasattr(wec, "_current_block_reward"):
            return float(wec._current_block_reward(height))  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        return float(getattr(wec, "initial_block_reward", 0.0))
    except Exception:
        return 0.0


def _groups_root() -> Dict[str, Any]:
    led = _ledger()
    return led.setdefault("groups", {"groups": {}})


def _groups() -> Dict[str, Dict[str, Any]]:
    root = _groups_root()
    g = root.setdefault("groups", {})
    if not isinstance(g, dict):
        root["groups"] = {}
        g = root["groups"]
    return g


def _get_group(group_id: str) -> Dict[str, Any]:
    g = _groups().get(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="group_not_found")
    if not isinstance(g, dict):
        raise HTTPException(status_code=500, detail="group_corrupt")
    return g


def _get_user_id(request: Request) -> str:
    uid = (request.headers.get("X-WeAll-User") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="missing_x_weall_user")
    return uid


def _resolve_multisig_policy(group: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns: {"signers": [...], "threshold": int}

    Priority:
    1) group.multisig.signers + threshold when configured
    2) if emissaries exist: signers=emissaries, threshold=min(3, len(signers))
    3) else: signer=[created_by], threshold=1  (bootstrap/dev safe fallback)
    """
    ms = group.get("multisig") or {}
    signers = list(ms.get("signers") or [])
    threshold = int(ms.get("threshold") or 0)

    if signers and threshold > 0:
        return {"signers": signers, "threshold": threshold}

    emissaries = list(group.get("emissaries") or [])
    if emissaries:
        return {"signers": emissaries, "threshold": max(1, min(3, len(emissaries)))}

    created_by = (group.get("created_by") or "").strip()
    if created_by:
        return {"signers": [created_by], "threshold": 1}

    return {"signers": [], "threshold": 0}


def _require_signer(user_id: str, policy: Dict[str, Any]) -> None:
    signers = set(policy.get("signers") or [])
    if user_id not in signers:
        raise HTTPException(status_code=403, detail="not_authorized_signer")


def _transfer_from_treasury(to_account: str, amount: float) -> None:
    """
    Move balance from TREASURY_ACCOUNT to to_account.

    Does NOT change total_issued (this is spending, not minting).
    """
    wec = _wecoin()
    if wec is None:
        raise HTTPException(status_code=500, detail="wecoin_runtime_missing")

    try:
        amt = float(amount)
    except Exception:
        raise HTTPException(status_code=400, detail="bad_amount")

    if amt <= 0:
        raise HTTPException(status_code=400, detail="amount_must_be_positive")

    if not to_account or not str(to_account).strip():
        raise HTTPException(status_code=400, detail="missing_to_account")

    to_account = str(to_account).strip()

    # Ensure balances map exists
    balances = getattr(wec, "balances", None)
    if not isinstance(balances, dict):
        raise HTTPException(status_code=500, detail="wecoin_balances_missing")

    treasury_bal = float(balances.get(TREASURY_ACCOUNT, 0.0))
    if treasury_bal + 1e-12 < amt:
        raise HTTPException(status_code=400, detail="insufficient_treasury_funds")

    balances[TREASURY_ACCOUNT] = treasury_bal - amt
    balances[to_account] = float(balances.get(to_account, 0.0)) + amt


def _treasury_root() -> Dict[str, Any]:
    led = _ledger()
    return led.setdefault("treasury", {})


def _group_spends() -> Dict[str, Any]:
    root = _treasury_root()
    spends = root.setdefault("group_spends", {})
    if not isinstance(spends, dict):
        root["group_spends"] = {}
        spends = root["group_spends"]
    return spends


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TreasuryMetaResponse(BaseModel):
    ok: bool = True
    token_symbol: str = Field("WEC", description="Human-readable token ticker.")
    max_supply: float
    total_issued: float
    initial_block_reward: float
    current_block_reward: float
    block_interval_seconds: int
    halving_interval_seconds: int
    blocks_per_epoch: int
    bootstrap_mode: bool
    pool_split_bps: Dict[str, int]


class TreasuryPoolsResponse(BaseModel):
    ok: bool = True
    treasury_account: str = Field(TREASURY_ACCOUNT)
    treasury_balance: float
    total_issued: float
    pool_split_bps: Dict[str, int]
    last_update: Optional[int] = None


class GroupSpendProposeBody(BaseModel):
    group_id: str = Field(..., min_length=4)
    to_account: str = Field(..., min_length=2)
    amount: float = Field(..., gt=0)
    memo: str = Field("", max_length=280)


class GroupSpendSignBody(BaseModel):
    spend_id: str = Field(..., min_length=6)
    note: str = Field("", max_length=280)


class GroupSpendExecuteBody(BaseModel):
    spend_id: str = Field(..., min_length=6)


# ---------------------------------------------------------------------------
# Routes: Meta / Pools
# ---------------------------------------------------------------------------

@router.get("/meta", response_model=TreasuryMetaResponse)
def get_treasury_meta() -> TreasuryMetaResponse:
    wec = _wecoin()

    if wec is not None:
        max_supply = float(getattr(wec, "max_supply", 0.0))
        total_issued = float(getattr(wec, "total_issued", 0.0))
        initial_block_reward = float(getattr(wec, "initial_block_reward", 0.0))
        block_interval_seconds = int(getattr(wec, "block_interval_seconds", 600))
        halving_interval_seconds = int(getattr(wec, "halving_interval_seconds", 0))
        pool_split = getattr(wec, "pool_split", {}) or {}
    else:
        max_supply = 21_000_000.0
        total_issued = 0.0
        initial_block_reward = 100.0
        block_interval_seconds = 600
        halving_interval_seconds = 2 * 365 * 24 * 60 * 60
        pool_split = {
            "validators": 0.20,
            "jurors": 0.20,
            "creators": 0.20,
            "operators": 0.20,
            "treasury": 0.20,
        }

    current_block_reward = _current_block_reward(wec)
    blocks_per_epoch = int(getattr(executor, "blocks_per_epoch", 100))
    bootstrap_mode = bool(getattr(executor, "bootstrap_mode", False))
    pool_split_bps = _pool_split_bps(pool_split)

    return TreasuryMetaResponse(
        max_supply=max_supply,
        total_issued=total_issued,
        initial_block_reward=initial_block_reward,
        current_block_reward=current_block_reward,
        block_interval_seconds=block_interval_seconds,
        halving_interval_seconds=halving_interval_seconds,
        blocks_per_epoch=blocks_per_epoch,
        bootstrap_mode=bootstrap_mode,
        pool_split_bps=pool_split_bps,
    )


@router.get("/pools", response_model=TreasuryPoolsResponse)
def get_treasury_pools() -> TreasuryPoolsResponse:
    wec = _wecoin()

    if wec is not None:
        treasury_balance = float(wec.get_balance(TREASURY_ACCOUNT))
        total_issued = float(getattr(wec, "total_issued", 0.0))
        pool_split = getattr(wec, "pool_split", {}) or {}
    else:
        treasury_balance = 0.0
        total_issued = 0.0
        pool_split = {
            "validators": 0.20,
            "jurors": 0.20,
            "creators": 0.20,
            "operators": 0.20,
            "treasury": 0.20,
        }

    return TreasuryPoolsResponse(
        treasury_balance=treasury_balance,
        total_issued=total_issued,
        pool_split_bps=_pool_split_bps(pool_split),
        last_update=None,
    )


# ---------------------------------------------------------------------------
# Routes: Group spend (multisig)
# ---------------------------------------------------------------------------

@router.post("/group_spend/propose")
def group_spend_propose(body: GroupSpendProposeBody, request: Request):
    user_id = _get_user_id(request)
    group = _get_group(body.group_id)

    policy = _resolve_multisig_policy(group)
    _require_signer(user_id, policy)

    spend_id = secrets.token_hex(8)
    spends = _group_spends()

    rec = {
        "id": spend_id,
        "group_id": body.group_id,
        "to_account": str(body.to_account).strip(),
        "amount": float(body.amount),
        "memo": body.memo or "",
        "proposed_by": user_id,
        "proposed_at": _now_ts(),
        "status": "proposed",
        "policy": {
            "signers": list(policy.get("signers") or []),
            "threshold": int(policy.get("threshold") or 0),
        },
        "signatures": {},  # signer -> {at, note}
        "executed_at": None,
        "executed_by": None,
    }
    spends[spend_id] = rec

    return {"ok": True, "spend": rec}


@router.get("/group_spend/list")
def group_spend_list(group_id: Optional[str] = None):
    spends = _group_spends()
    items = list(spends.values())
    if group_id:
        items = [s for s in items if s.get("group_id") == group_id]
    # newest first
    items.sort(key=lambda x: float(x.get("proposed_at") or 0), reverse=True)
    return {"ok": True, "spends": items}


@router.post("/group_spend/sign")
def group_spend_sign(body: GroupSpendSignBody, request: Request):
    user_id = _get_user_id(request)
    spends = _group_spends()
    rec = spends.get(body.spend_id)
    if not rec:
        raise HTTPException(status_code=404, detail="spend_not_found")
    if rec.get("status") != "proposed":
        raise HTTPException(status_code=400, detail="spend_not_proposable")

    group = _get_group(str(rec.get("group_id")))
    policy = rec.get("policy") or _resolve_multisig_policy(group)

    _require_signer(user_id, policy)

    sigs = rec.setdefault("signatures", {})
    sigs[user_id] = {"at": _now_ts(), "note": body.note or ""}

    return {"ok": True, "spend": rec, "signatures": sigs, "count": len(sigs)}


@router.post("/group_spend/execute")
def group_spend_execute(body: GroupSpendExecuteBody, request: Request):
    user_id = _get_user_id(request)
    spends = _group_spends()
    rec = spends.get(body.spend_id)
    if not rec:
        raise HTTPException(status_code=404, detail="spend_not_found")
    if rec.get("status") != "proposed":
        raise HTTPException(status_code=400, detail="spend_not_executable")

    group = _get_group(str(rec.get("group_id")))
    policy = rec.get("policy") or _resolve_multisig_policy(group)
    _require_signer(user_id, policy)

    sigs = rec.get("signatures") or {}
    threshold = int((policy.get("threshold") or 0))
    if threshold <= 0:
        raise HTTPException(status_code=400, detail="multisig_threshold_invalid")

    if len(sigs) < threshold:
        raise HTTPException(
            status_code=400,
            detail=f"insufficient_signatures:{len(sigs)}/{threshold}",
        )

    _transfer_from_treasury(str(rec.get("to_account")), float(rec.get("amount") or 0.0))

    rec["status"] = "executed"
    rec["executed_at"] = _now_ts()
    rec["executed_by"] = user_id
    return {"ok": True, "spend": rec}
