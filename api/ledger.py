# api/ledger.py

from fastapi import APIRouter

router = APIRouter(
    prefix="/ledger",
    tags=["Ledger"]
)

# In-memory placeholder ledger
ledger_state = {
    "accounts": {},
    "balances": {},
}

# ------------------------
# Endpoints
# ------------------------

@router.get("/")
def get_ledger_status():
    """
    Basic health/status endpoint for the ledger module
    """
    return {"status": "ok", "message": "Ledger module is active"}


@router.post("/create_account/{user_id}")
def create_account(user_id: str):
    """
    Create a new account with zero balance
    """
    if user_id in ledger_state["accounts"]:
        return {"ok": False, "error": "account_already_exists"}
    
    ledger_state["accounts"][user_id] = 0
    ledger_state["balances"][user_id] = 0
    return {"ok": True, "user_id": user_id}


@router.get("/balance/{user_id}")
def get_balance(user_id: str):
    """
    Get the balance of a user account
    """
    if user_id not in ledger_state["balances"]:
        return {"ok": False, "error": "account_not_found"}
    return {"ok": True, "balance": ledger_state["balances"][user_id]}


@router.post("/deposit/{user_id}/{amount}")
def deposit(user_id: str, amount: float):
    """
    Deposit an amount into a user account
    """
    if user_id not in ledger_state["balances"]:
        return {"ok": False, "error": "account_not_found"}
    
    ledger_state["balances"][user_id] += amount
    return {"ok": True, "balance": ledger_state["balances"][user_id]}


@router.post("/transfer/{from_user}/{to_user}/{amount}")
def transfer(from_user: str, to_user: str, amount: float):
    """
    Transfer funds from one account to another
    """
    if from_user not in ledger_state["balances"]:
        return {"ok": False, "error": "from_account_not_found"}
    if to_user not in ledger_state["balances"]:
        return {"ok": False, "error": "to_account_not_found"}
    if ledger_state["balances"][from_user] < amount:
        return {"ok": False, "error": "insufficient_funds"}
    
    ledger_state["balances"][from_user] -= amount
    ledger_state["balances"][to_user] += amount
    return {"ok": True, "from_balance": ledger_state["balances"][from_user], "to_balance": ledger_state["balances"][to_user]}
