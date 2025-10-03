"""
LedgerRuntime with Bitcoin-like halving and bootstrap validator safeguard.
"""

import random, time
from typing import Dict, List, Any, Optional

TREASURY_ACCOUNT = "treasury"

INITIAL_EPOCH_REWARD = 100.0
HALVING_INTERVAL = 2 * 365 * 24 * 60 * 60  # 2 years


class WeCoinLedger:
    def __init__(self):
        self.balances: Dict[str, float] = {TREASURY_ACCOUNT: 0.0}
        self.pools: Dict[str, Dict[str, Any]] = {
            "creators":   {"members": []},
            "jurors":     {"members": []},
            "operators":  {"members": []},
            "validators": {"members": []},
        }
        self.genesis_time = int(time.time())

    # ---- accounts ----
    def create_account(self, account: str):
        if account not in self.balances:
            self.balances[account] = 0.0

    def deposit(self, account: str, amount: float):
        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        self.create_account(account)
        self.balances[account] += float(amount)
        return {"ok": True, "balance": self.balances[account]}

    def withdraw(self, account: str, amount: float):
        if amount <= 0:
            return {"ok": False, "error": "invalid_amount"}
        bal = self.balances.get(account, 0.0)
        if bal < amount:
            return {"ok": False, "error": "insufficient_funds"}
        self.balances[account] = bal - float(amount)
        return {"ok": True, "balance": self.balances[account]}

    def transfer(self, src: str, dst: str, amount: float):
        w = self.withdraw(src, amount)
        if not w.get("ok"):
            return w
        return self.deposit(dst, amount)

    # ---- pools ----
    def add_to_pool(self, pool_name: str, account: str):
        if pool_name not in self.pools:
            self.pools[pool_name] = {"members": []}
        self.create_account(account)
        if account not in self.pools[pool_name]["members"]:
            self.pools[pool_name]["members"].append(account)

    def remove_from_pool(self, pool_name: str, account: str):
        if pool_name in self.pools and account in self.pools[pool_name]["members"]:
            self.pools[pool_name]["members"].remove(account)

    # ---- reward logic ----
    def current_epoch_reward(self) -> float:
        elapsed = int(time.time()) - self.genesis_time
        halvings = elapsed // HALVING_INTERVAL
        return INITIAL_EPOCH_REWARD / (2 ** halvings)

    def distribute_epoch_rewards(self, current_epoch: int, bootstrap_mode: bool = False) -> Dict[str, Optional[str]]:
        winners: Dict[str, Optional[str]] = {}
        pools = list(self.pools.keys())
        if not pools:
            return winners

        per_pool_reward = self.current_epoch_reward() / len(pools)

        for pool in pools:
            members: List[str] = self.pools[pool]["members"]
            if not members:
                winners[pool] = None
                continue

            winner = random.choice(members)
            winners[pool] = winner

            # ✅ Suppress validator rewards during bootstrap
            if pool == "validators" and bootstrap_mode:
                continue

            self.deposit(winner, per_pool_reward)

        return winners


class LedgerRuntime:
    def __init__(self):
        self.current_epoch: int = 0
        self.wecoin = WeCoinLedger()

    def advance_epoch(self, bootstrap_mode: bool = False) -> Dict[str, Optional[str]]:
        self.current_epoch += 1
        return self.wecoin.distribute_epoch_rewards(self.current_epoch, bootstrap_mode=bootstrap_mode)
