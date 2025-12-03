"""
weall_node/api/ledger.py
--------------------------------------------------
Read-only ledger + balances + cryptographic proofs.

- Return a full ledger snapshot
- Get a user's token balance
- List commitments signed by the node (epoch Merkle roots)
- Retrieve a Merkle proof for a specific account
"""

from fastapi import APIRouter, HTTPException

from ..weall_executor import executor

# All routes under /ledger/...
router = APIRouter(prefix="/ledger", tags=["ledger"])


def _ledger():
    """Safe access to the executor's ledger dict."""
    led = getattr(executor, "ledger", None)
    if led is None:
        led = {}
        executor.ledger = led
    return led


@router.get("/")
def get_full_ledger():
    """
    Full ledger snapshot plus a couple of convenience fields.

    This is intentionally read-only and light:
    - block_height is derived from len(chain)
    - epoch falls back to 0 if the runtime hasn't started tracking it yet
    """
    try:
        ledger = _ledger()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ledger_unavailable:{e!s}")

    chain = ledger.get("chain") or []
    height = len(chain)

    epoch = 0
    try:
        epoch = int(getattr(executor, "current_epoch", 0))
    except Exception:
        epoch = 0

    return {
        "ok": True,
        "block_height": int(height),
        "epoch": epoch,
        "ledger": ledger,
    }


@router.get("/balance/{user_id}")
def get_balance(user_id: str):
    """
    Return the user's token balance, defaulting to 0.

    Profile calls this endpoint as /ledger/balance/{email}.
    """
    user_id = (user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id_required")

    # Prefer the executor helper if present (keeps WeCoin in sync)
    try:
        bal = executor.get_balance(user_id)
    except AttributeError:
        # Legacy behaviour: read from ledger.balances / ledger.accounts
        ledger = _ledger()
        balances = ledger.get("balances") or ledger.get("accounts") or {}
        try:
            bal = balances.get(user_id, 0)
        except AttributeError:
            bal = 0

    try:
        bal = float(bal)
    except Exception:
        bal = 0.0

    # Attach wallet metadata if present (derived from email+password at signup)
    wallet = None
    try:
        led_full = getattr(executor, "ledger", {}) or {}
        accounts = led_full.get("accounts") or {}
        acct = accounts.get(user_id) or {}
        wallet = acct.get("wallet")
    except Exception:
        wallet = None

    return {"ok": True, "user_id": user_id, "balance": bal, "wallet": wallet}


@router.get("/commitments")
def get_commitments():
    """Signed epoch commitments (Merkle roots) with signatures and pubkey."""
    try:
        commits = executor.get_commitments()
    except AttributeError:
        # Older runtimes may not expose commitments yet
        commits = []
    return {"ok": True, "commitments": commits}


@router.get("/proof/{user_id}")
def merkle_proof(user_id: str):
    """Return Merkle proof for the user's balance under the latest snapshot."""
    user_id = (user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id_required")

    try:
        proof = executor.get_merkle_proof(user_id)
    except AttributeError:
        raise HTTPException(
            status_code=501, detail="merkle_proofs_not_implemented"
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="user_not_in_snapshot")

    return {"ok": True, "user_id": user_id, "proof": proof}
