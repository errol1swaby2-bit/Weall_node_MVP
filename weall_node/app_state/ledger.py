"""
LedgerState – production-leaning, pure-Python
- Account balances (float for MVP)
- Fees -> treasury
- Mint/Burn (restricted hooks – call from governance pallets only)
- Simple reward distribution hook
- Event persistence into ChainState
- JSON persistence across restarts
"""

from typing import Dict, Any
import time, json, os
from weall_node.app_state.chain import ChainState

TREASURY_ACCOUNT = "treasury"
FEE_RATE = 0.0025
LEDGER_FILE = "ledger.json"


class LedgerState:
    def __init__(self, chain: ChainState):
        self.balances: Dict[str, float] = {TREASURY_ACCOUNT: 0.0}
        self.chain = chain
        self.load()

    # ---------- helpers ----------
    def _get(self, acct: str) -> float:
        return float(self.balances.get(acct, 0.0))

    def _set(self, acct: str, amt: float) -> None:
        self.balances[acct] = float(amt)
        self.persist()

    def _credit(self, acct: str, amt: float) -> None:
        self._set(acct, self._get(acct) + float(amt))

    def _debit(self, acct: str, amt: float) -> bool:
        if self._get(acct) < amt:
            return False
        self._set(acct, self._get(acct) - amt)
        return True

    def _persist_event(self, etype: str, payload: dict) -> None:
        tx = {"ts": int(time.time()), "type": etype, "payload": payload}
        self.chain.add_block([tx])

    # ---------- persistence ----------
    def persist(self):
        with open(LEDGER_FILE, "w") as f:
            json.dump(self.balances, f, indent=2)

    def load(self):
        if os.path.exists(LEDGER_FILE):
            with open(LEDGER_FILE) as f:
                self.balances = json.load(f)

    # ---------- public API ----------
    def create_account(self, account: str) -> Dict[str, Any]:
        """Ensure an account exists with 0 balance."""
        if account not in self.balances:
            self.balances[account] = 0.0
            self.persist()
            self._persist_event("create_account", {"account": account})
        return {"ok": True, "account": account, "balance": self._get(account)}

    def deposit(self, account: str, amount: float) -> Dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        self._credit(account, amount)
        self._persist_event("deposit", {"account": account, "amount": amount})
        return {"ok": True, "account": account, "new_balance": self._get(account)}

    def transfer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            sender = payload["from"]
            receiver = payload["to"]
            amount = float(payload["amount"])
        except Exception:
            return {"ok": False, "error": "bad_payload"}

        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}

        fee = max(0.0, amount * FEE_RATE)
        total = amount + fee
        if not self._debit(sender, total):
            return {"ok": False, "error": "insufficient_funds"}

        self._credit(receiver, amount)
        self._credit(TREASURY_ACCOUNT, fee)
        self._persist_event("transfer", {
            "from": sender,
            "to": receiver,
            "amount": amount,
            "fee": fee
        })
        return {
            "ok": True,
            "from": sender,
            "to": receiver,
            "amount": amount,
            "fee": fee,
            "treasury": self._get(TREASURY_ACCOUNT),
            "sender_balance": self._get(sender),
            "receiver_balance": self._get(receiver),
        }

    # ---------- governance-only hooks ----------
    def mint(self, account: str, amount: float) -> Dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        self._credit(account, amount)
        self._persist_event("mint", {"account": account, "amount": amount})
        return {"ok": True, "account": account, "new_balance": self._get(account)}

    def burn(self, account: str, amount: float) -> Dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        if not self._debit(account, amount):
            return {"ok": False, "error": "insufficient_funds"}
        self._persist_event("burn", {"account": account, "amount": amount})
        return {"ok": True, "account": account, "new_balance": self._get(account)}

    def treasury_payout(self, to: str, amount: float) -> Dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        if not self._debit(TREASURY_ACCOUNT, amount):
            return {"ok": False, "error": "treasury_insufficient"}
        self._credit(to, amount)
        self._persist_event("treasury_payout", {"to": to, "amount": amount})
        return {"ok": True, "to": to, "amount": amount}

    def distribute_rewards(self, rewards: Dict[str, float]) -> Dict[str, Any]:
        for acct, amt in rewards.items():
            if amt > 0:
                self._credit(acct, amt)
        self._persist_event("rewards", rewards)
        return {"ok": True}

    # ---------- event hooks ----------
    def record_mint_event(self, user_id: str, nft_id: str):
        self._persist_event("nft_mint", {"user_id": user_id, "nft_id": nft_id})

    def record_transfer_event(self, old_owner: str, new_owner: str, nft_id: str):
        self._persist_event("nft_transfer", {"from": old_owner, "to": new_owner, "nft_id": nft_id})

    def record_burn_event(self, owner: str, nft_id: str):
        self._persist_event("nft_burn", {"owner": owner, "nft_id": nft_id})

    def record_slash(self, user_id: str, amount: float, reason: str):
        self._persist_event("slash", {"user_id": user_id, "amount": amount, "reason": reason})
