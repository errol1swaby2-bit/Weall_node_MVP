#!/usr/bin/env python3
"""
weall_node.app_state.ledger
---------------------------

Persistent token ledger state for WeAll MVP.

This ledger is minimal:
- Maintains account balances
- Tracks pool memberships and eligibility flags
- Provides safe JSON persistence
- Used by WeAllExecutor.ledger for reward distribution
"""

import os
import json
from collections import defaultdict
from typing import Dict, Set


class LedgerState:
    def __init__(self):
        self.accounts: Dict[str, float] = defaultdict(float)
        self.pools: Dict[str, Set[str]] = defaultdict(set)
        self.eligible: Dict[str, bool] = defaultdict(lambda: True)

    # ---------- Core ----------
    def deposit(self, user: str, amount: float):
        self.accounts[user] += float(amount)

    def balance(self, user: str) -> float:
        return float(self.accounts.get(user, 0.0))

    def transfer(self, from_user: str, to_user: str, amount: float) -> bool:
        amount = float(amount)
        if self.accounts[from_user] >= amount:
            self.accounts[from_user] -= amount
            self.accounts[to_user] += amount
            return True
        return False

    # ---------- Pools ----------
    def add_to_pool(self, name: str, user: str):
        self.pools[name].add(user)

    def remove_from_pool(self, name: str, user: str):
        self.pools[name].discard(user)

    def set_eligible(self, user: str, ok: bool = True):
        self.eligible[user] = bool(ok)

    # ---------- Persistence ----------
    def save(self, path: str):
        data = {
            "accounts": self.accounts,
            "pools": {k: list(v) for k, v in self.pools.items()},
            "eligible": self.eligible,
        }
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[ledger.save] {e}")

    def load(self, path: str):
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.accounts = defaultdict(float, data.get("accounts", {}))
            self.pools = defaultdict(set, {k: set(v) for k, v in data.get("pools", {}).items()})
            self.eligible = defaultdict(lambda: True, data.get("eligible", {}))
        except Exception as e:
            print(f"[ledger.load] {e}")

    # ---------- Audit ----------
    def audit(self) -> bool:
        """Basic integrity check: all balances ≥ 0."""
        for u, bal in self.accounts.items():
            if bal < 0:
                print(f"[ledger.audit] ❌ Negative balance: {u}={bal}")
                return False
        return True

# ---- compatibility alias ----
WeCoinLedger = LedgerState
__all__ = ["LedgerState", "WeCoinLedger"]
