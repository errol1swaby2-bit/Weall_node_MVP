# api/messaging.py
from fastapi import APIRouter

router = APIRouter(prefix="/messaging", tags=["Messaging"])

messages = {}

@router.post("/send/{from_user}/{to_user}")
def send(from_user: str, to_user: str, message: str):
    messages.setdefault(to_user, []).append({"from": from_user, "text": message})
    return {"ok": True}

@router.get("/inbox/{user_id}")
def inbox(user_id: str):
    return {"messages": messages.get(user_id, [])}
