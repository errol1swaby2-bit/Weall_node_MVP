# api/treasury.py
from fastapi import APIRouter
from weall_node.api.ledger import ledger_state

router = APIRouter(prefix="/treasury", tags=["Treasury"])

treasury_state = {
    "funds": 0
}

@router.get("/")
def status():
    return {"status": "ok", "funds": treasury_state["funds"]}

@router.post("/deposit/{user_id}/{amount}")
def deposit(user_id: str, amount: float):
    if user_id not in ledger_state["balances"]:
        return {"ok": False, "error": "user_not_found"}
    treasury_state["funds"] += amount
    ledger_state["balances"][user_id] -= amount
    return {"ok": True, "treasury_funds": treasury_state["funds"]}
