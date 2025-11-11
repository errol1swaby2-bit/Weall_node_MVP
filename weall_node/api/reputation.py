# api/reputation.py
from fastapi import APIRouter

router = APIRouter(prefix="/reputation", tags=["Reputation"])

reputation_scores = {}


@router.post("/grant/{user_id}/{amount}")
def grant(user_id: str, amount: int):
    reputation_scores[user_id] = reputation_scores.get(user_id, 0) + amount
    return {"ok": True, "reputation": reputation_scores[user_id]}


@router.post("/slash/{user_id}/{amount}")
def slash(user_id: str, amount: int):
    reputation_scores[user_id] = reputation_scores.get(user_id, 0) - amount
    return {"ok": True, "reputation": reputation_scores[user_id]}
