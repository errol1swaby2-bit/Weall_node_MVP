from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from weall_node.weall_executor import executor
from weall_node.weall_runtime import ReputationRuntime

router = APIRouter(prefix="/reputation", tags=["Reputation"])


class ReputationEvent(BaseModel):
    user_id: str
    delta: float
    reason: str | None = None


def _runtime() -> ReputationRuntime:
    # Bind runtime to the canonical executor ledger.
    # If for some reason executor has no ledger yet, we fall back to an empty dict.
    state = getattr(executor, "ledger", None)
    if state is None:
        state = {}
    return ReputationRuntime(state)


@router.get("/{user_id}")
def get_reputation(user_id: str):
    rt = _runtime()
    return {
        "ok": True,
        "user_id": user_id,
        "reputation": rt.get(user_id),
    }


@router.post("/event")
def apply_event(evt: ReputationEvent):
    # Guardrail: block absurd rep swings in one call.
    if abs(evt.delta) > 0.5:
        raise HTTPException(status_code=400, detail="delta too large for single event")

    rt = _runtime()
    new_score = rt.apply_delta(evt.user_id, evt.delta, evt.reason or "impact_event")

    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()

    return {
        "ok": True,
        "user_id": evt.user_id,
        "reputation": new_score,
        "thresholds": {
            "tier3_min": 0.75,
            "terminal": -1.0,
        },
    }


@router.post("/grant/{user_id}/{amount}")
def legacy_grant(user_id: str, amount: float):
    """
    Legacy positive adjustment helper.
    """
    rt = _runtime()
    new_score = rt.apply_delta(user_id, float(amount), "legacy_grant")

    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()

    return {"ok": True, "user_id": user_id, "reputation": new_score}


@router.post("/slash/{user_id}/{amount}")
def legacy_slash(user_id: str, amount: float):
    """
    Legacy negative adjustment helper.
    """
    rt = _runtime()
    new_score = rt.apply_delta(user_id, -float(amount), "legacy_slash")

    save_state = getattr(executor, "save_state", None)
    if callable(save_state):
        save_state()

    return {"ok": True, "user_id": user_id, "reputation": new_score}
