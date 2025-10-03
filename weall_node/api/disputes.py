# api/disputes.py
from fastapi import APIRouter

router = APIRouter(prefix="/disputes", tags=["Disputes"])

disputes = {}
counter = 1

@router.post("/create")
def create_dispute(user_id: str, post_id: int, description: str):
    global counter
    did = counter
    disputes[did] = {"user": user_id, "post_id": post_id, "description": description, "status": "open"}
    counter += 1
    return {"ok": True, "dispute_id": did}

@router.get("/{dispute_id}")
def get_dispute(dispute_id: int):
    return disputes.get(dispute_id, {"error": "not_found"})
