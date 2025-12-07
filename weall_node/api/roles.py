"""
weall_node/api/roles.py
--------------------------------------------------
Role + validator/juror/operator preferences, keyed by PoH id.

- Requires X-WeAll-User header for identity
- Tiers are enforced from the PoH module:

    Tier 0: read-only crawlers / exchanges
    Tier 1: email verified — like/comment/message only
    Tier 2: async verified human — can post + join groups
    Tier 3: live jury verified human — full protocol access

- Only Tier 3 can change juror / operator / validator settings.

Ledger layout:

executor.ledger["roles"] = {
    "by_poh": {
        "<poh_id>": {
            "poh_id": str,
            "tier": int,
            "validator": {
                "enabled": bool,
                "run_in_background": bool,
                "wifi_only": bool,
                "only_while_charging": bool,
                "intensity": str,  # "low" | "medium" | "high"
                "since": int | None,
            },
            "juror": {
                "enabled": bool,
                "since": int | None,
            },
            "operator": {
                "enabled": bool,
                "since": int | None,
            },
            "created_at": int,
            "updated_at": int,
        }
    }
}
"""

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..weall_executor import executor

router = APIRouter()


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _get_poh_id_from_header(request: Request) -> str:
    poh_id = request.headers.get("X-WeAll-User")
    if not poh_id:
        raise HTTPException(status_code=400, detail="Missing X-WeAll-User header")
    return poh_id


def _get_poh_tier(poh_id: str) -> int:
    """
    Look up the current PoH tier from the ledger.
    Returns 0 if no record exists.
    """
    ledger = executor.ledger
    poh_root = ledger.setdefault("poh", {})
    records = poh_root.setdefault("records", {})
    rec = records.get(poh_id)
    if not rec:
        return 0
    try:
        return int(rec.get("tier") or 0)
    except Exception:
        return 0


def _ensure_roles_record(poh_id: str, tier: int):
    """
    Ensure a roles record exists for this poh_id, with sensible defaults.

    - validator.enabled:
        * True by default at Tier 3
        * False otherwise
    - validator.run_in_background: False
    - validator.wifi_only: True
    - validator.only_while_charging: False
    - validator.intensity: "medium"
    - juror.enabled: False (opt-in)
    - operator.enabled: False (opt-in)
    """
    now = int(time.time())
    ledger = executor.ledger
    roles_root = ledger.setdefault("roles", {})
    by_poh = roles_root.setdefault("by_poh", {})

    rec = by_poh.get(poh_id)
    if rec is None:
        default_validator_enabled = tier >= 3
        rec = {
            "poh_id": poh_id,
            "tier": tier,
            "validator": {
                "enabled": default_validator_enabled,
                "run_in_background": False,
                "wifi_only": True,
                "only_while_charging": False,
                "intensity": "medium",
                "since": now if default_validator_enabled else None,
            },
            "juror": {
                "enabled": False,
                "since": None,
            },
            "operator": {
                "enabled": False,
                "since": None,
            },
            "created_at": now,
            "updated_at": now,
        }
        by_poh[poh_id] = rec

    # Always sync tier with current PoH tier
    if rec.get("tier") != tier:
        rec["tier"] = tier

        # If tier dropped below 3, force-disable privileged roles
        if tier < 3:
            v = rec.get("validator", {})
            v["enabled"] = False
            v["run_in_background"] = False
            v["since"] = None

            j = rec.get("juror", {})
            j["enabled"] = False
            j["since"] = None

            o = rec.get("operator", {})
            o["enabled"] = False
            o["since"] = None

        # If tier upgraded to 3 and validator was never enabled, default it ON
        elif tier >= 3:
            v = rec.setdefault("validator", {})
            if not v.get("enabled") and v.get("since") is None:
                v["enabled"] = True
                v["since"] = now

        rec["updated_at"] = now

    return rec


# ------------------------------------------------------------
# Models
# ------------------------------------------------------------

class ValidatorSettings(BaseModel):
    enabled: bool
    run_in_background: bool
    wifi_only: bool
    only_while_charging: bool
    intensity: str = Field(pattern="^(low|medium|high)$")
    since: Optional[int]


class JurorSettings(BaseModel):
    enabled: bool
    since: Optional[int]


class OperatorSettings(BaseModel):
    enabled: bool
    since: Optional[int]


class RolesEnvelope(BaseModel):
    ok: bool = True
    poh_id: str
    tier: int
    validator: ValidatorSettings
    juror: JurorSettings
    operator: OperatorSettings


class ValidatorUpdate(BaseModel):
    enabled: Optional[bool] = None
    run_in_background: Optional[bool] = None
    wifi_only: Optional[bool] = None
    only_while_charging: Optional[bool] = None
    intensity: Optional[str] = Field(
        default=None,
        pattern="^(low|medium|high)$",
    )


class JurorUpdate(BaseModel):
    enabled: Optional[bool] = None


class OperatorUpdate(BaseModel):
    enabled: Optional[bool] = None


class RolesUpdate(BaseModel):
    validator: Optional[ValidatorUpdate] = None
    juror: Optional[JurorUpdate] = None
    operator: Optional[OperatorUpdate] = None


# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------

@router.get("/me", response_model=RolesEnvelope)
def get_my_roles(request: Request) -> RolesEnvelope:
    poh_id = _get_poh_id_from_header(request)
    tier = _get_poh_tier(poh_id)
    if tier <= 0:
        raise HTTPException(status_code=404, detail="No PoH record for this user")

    rec = _ensure_roles_record(poh_id, tier)

    return RolesEnvelope(
        poh_id=poh_id,
        tier=tier,
        validator=ValidatorSettings(**rec["validator"]),
        juror=JurorSettings(**rec["juror"]),
        operator=OperatorSettings(**rec["operator"]),
    )


@router.post("/me", response_model=RolesEnvelope)
def update_my_roles(payload: RolesUpdate, request: Request) -> RolesEnvelope:
    poh_id = _get_poh_id_from_header(request)
    tier = _get_poh_tier(poh_id)
    if tier < 3:
        # Only Tier 3 can change these knobs at all
        raise HTTPException(
            status_code=403,
            detail="Tier 3 is required to change juror/operator/validator settings",
        )

    rec = _ensure_roles_record(poh_id, tier)
    now = int(time.time())
    changed = False

    # Validator updates
    if payload.validator is not None:
        v = rec.setdefault("validator", {})
        if payload.validator.enabled is not None:
            new_val = bool(payload.validator.enabled)
            if v.get("enabled") is not new_val:
                v["enabled"] = new_val
                changed = True
                if new_val and v.get("since") is None:
                    v["since"] = now
                if not new_val:
                    v["since"] = None

        if payload.validator.run_in_background is not None:
            new_val = bool(payload.validator.run_in_background)
            if v.get("run_in_background") is not new_val:
                v["run_in_background"] = new_val
                changed = True

        if payload.validator.wifi_only is not None:
            new_val = bool(payload.validator.wifi_only)
            if v.get("wifi_only") is not new_val:
                v["wifi_only"] = new_val
                changed = True

        if payload.validator.only_while_charging is not None:
            new_val = bool(payload.validator.only_while_charging)
            if v.get("only_while_charging") is not new_val:
                v["only_while_charging"] = new_val
                changed = True

        if payload.validator.intensity is not None:
            new_val = payload.validator.intensity
            if v.get("intensity") != new_val:
                v["intensity"] = new_val
                changed = True

    # Juror updates
    if payload.juror is not None and payload.juror.enabled is not None:
        j = rec.setdefault("juror", {})
        new_val = bool(payload.juror.enabled)
        if j.get("enabled") is not new_val:
            j["enabled"] = new_val
            j["since"] = now if new_val else None
            changed = True

    # Operator updates
    if payload.operator is not None and payload.operator.enabled is not None:
        o = rec.setdefault("operator", {})
        new_val = bool(payload.operator.enabled)
        if o.get("enabled") is not new_val:
            o["enabled"] = new_val
            o["since"] = now if new_val else None
            changed = True

    if changed:
        rec["updated_at"] = now
        # executor is responsible for persisting ledger to disk

    return RolesEnvelope(
        poh_id=poh_id,
        tier=tier,
        validator=ValidatorSettings(**rec["validator"]),
        juror=JurorSettings(**rec["juror"]),
        operator=OperatorSettings(**rec["operator"]),
    )
