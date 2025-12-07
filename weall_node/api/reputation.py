"""
weall_node/api/reputation.py
--------------------------------------------------
MVP reputation system for WeAll.

- Stores a simple numeric score per user.
- Keeps an append-only history of events (who, delta, reason, source).
- Provides an internal helper apply_reputation_event(...) that other
  modules (like api.disputes) can call without worrying about the ledger
  layout.

Ledger layout:

executor.ledger["reputation"] = {
    "scores": {
        "<user_id>": float,
        ...
    },
    "history": [
        {
            "user_id": str,
            "delta": float,
            "reason": str,
            "source": str,
            "meta": dict,
            "timestamp": int,
            "score_after": float,
        },
        ...
    ],
    "last_update": int,
}

If an older deployment stored reputation as a bare dict {user_id: score},
we upgrade it on first access to match the above layout.
"""

import time
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..weall_executor import executor

# NOTE: no prefix here; weall_api.py mounts this router at /reputation
router = APIRouter(tags=["Reputation"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _root() -> Dict[str, Any]:
    """
    Return the normalized reputation root object.

    Handles older layouts where executor.ledger["reputation"] was just a
    dict of {user_id: score}.
    """
    ledger = executor.ledger
    rep = ledger.get("reputation")

    # First run, nothing there yet: create fresh structure.
    if rep is None:
        rep = {"scores": {}, "history": [], "last_update": None}
        ledger["reputation"] = rep
        return rep

    # If it's already in the new shape, ensure required keys exist.
    if isinstance(rep, dict) and ("scores" in rep or "history" in rep):
        rep.setdefault("scores", {})
        rep.setdefault("history", [])
        rep.setdefault("last_update", None)
        return rep

    # If it's a bare dict of {user_id: score}, upgrade it.
    if isinstance(rep, dict):
        scores = {}
        for k, v in rep.items():
            try:
                scores[str(k)] = float(v)
            except Exception:
                continue
        upgraded = {"scores": scores, "history": [], "last_update": None}
        ledger["reputation"] = upgraded
        return upgraded

    # Fallback: if something weird, overwrite with an empty structure.
    upgraded = {"scores": {}, "history": [], "last_update": None}
    ledger["reputation"] = upgraded
    return upgraded


def _save():
    try:
        executor.save_state()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public helper for other modules
# ---------------------------------------------------------------------------


def apply_reputation_event(
    user_id: str,
    delta: float,
    *,
    reason: str,
    source: str = "system",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Adjust the reputation score for a user and append a history record.

    This is safe to import from other api modules:
        from . import reputation as reputation_api
        reputation_api.apply_reputation_event("user", +1.0, reason="...", source="disputes")
    """
    user_id = str(user_id)
    rep = _root()
    scores: Dict[str, float] = rep["scores"]
    history: List[Dict[str, Any]] = rep["history"]

    try:
        delta_f = float(delta)
    except Exception:
        delta_f = 0.0

    now = int(time.time())
    current = float(scores.get(user_id, 0.0))
    new_score = current + delta_f

    scores[user_id] = new_score
    event = {
        "user_id": user_id,
        "delta": delta_f,
        "reason": reason,
        "source": source,
        "meta": meta or {},
        "timestamp": now,
        "score_after": new_score,
    }
    history.append(event)
    rep["last_update"] = now

    _save()
    return event


# ---------------------------------------------------------------------------
# Models for API
# ---------------------------------------------------------------------------


class AdjustRequest(BaseModel):
    user_id: str = Field(..., description="User id / handle whose reputation to adjust.")
    delta: float = Field(..., description="Signed reputation change.")
    reason: str = Field(..., max_length=280)
    source: str = Field("manual", max_length=64)
    meta: Optional[Dict[str, Any]] = None


class ScoreResponse(BaseModel):
    user_id: str
    score: float
    history: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/meta")
def get_meta() -> Dict[str, Any]:
    rep = _root()
    scores: Dict[str, float] = rep["scores"]
    if scores:
        values = list(scores.values())
        total = len(values)
        avg = sum(values) / total
        return {
            "total_users": total,
            "avg_score": avg,
            "min_score": min(values),
            "max_score": max(values),
            "last_update": rep.get("last_update"),
        }
    else:
        return {
            "total_users": 0,
            "avg_score": 0.0,
            "min_score": 0.0,
            "max_score": 0.0,
            "last_update": rep.get("last_update"),
        }


@router.get("/", response_model=Dict[str, Any])
def list_scores(
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """
    Return the top N scores (by value, descending).
    """
    rep = _root()
    scores: Dict[str, float] = rep["scores"]
    sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    limited = sorted_items[:limit]
    return {
        "scores": [{"user_id": k, "score": v} for k, v in limited],
        "total": len(scores),
        "last_update": rep.get("last_update"),
    }


@router.get("/{user_id}", response_model=ScoreResponse)
def get_user_score(user_id: str) -> ScoreResponse:
    rep = _root()
    scores: Dict[str, float] = rep["scores"]
    history: List[Dict[str, Any]] = rep["history"]

    score = float(scores.get(user_id, 0.0))
    user_history = [ev for ev in history if ev.get("user_id") == user_id]

    return ScoreResponse(user_id=user_id, score=score, history=user_history)


@router.get("/me", response_model=ScoreResponse)
def get_me(request: Request, user_id: Optional[str] = None) -> ScoreResponse:
    """
    Simple helper endpoint.

    We try, in order:
      - query parameter user_id
      - X-WeAll-User header
      - X-User-Id header

    This keeps it flexible for your current frontend wiring.
    """
    uid = user_id
    if not uid:
        uid = request.headers.get("X-WeAll-User") or request.headers.get("X-User-Id")

    if not uid:
        raise HTTPException(status_code=400, detail="user_id_required")

    return get_user_score(uid)


@router.post("/adjust", response_model=ScoreResponse)
def adjust_score(payload: AdjustRequest) -> ScoreResponse:
    apply_reputation_event(
        payload.user_id,
        payload.delta,
        reason=payload.reason,
        source=payload.source,
        meta=payload.meta,
    )
    return get_user_score(payload.user_id)
