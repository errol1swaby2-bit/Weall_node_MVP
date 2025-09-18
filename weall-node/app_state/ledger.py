# app_state/ledger.py
import json
from collections import defaultdict

class Ledger:
    def __init__(self, persist_file=None):
        self.accounts = defaultdict(float)    # user -> balance
        self.persist_file = persist_file      # optional, for snapshotting
        self.pools = defaultdict(set)         # pool -> set(users)
        self.eligible = defaultdict(lambda: True)  # user -> eligibility flag

    # ---------------------------
    # Account management
    # ---------------------------
    def create_account(self, user_id):
        self.accounts.setdefault(user_id, 0.0)

    def deposit(self, user_id, amount):
        self.create_account(user_id)
        self.accounts[user_id] += amount
        return self.accounts[user_id]

    def transfer(self, from_user, to_user, amount):
        self.create_account(from_user)
        self.create_account(to_user)
        if self.accounts[from_user] >= amount:
            self.accounts[from_user] -= amount
            self.accounts[to_user] += amount
            return True
        return False

    def balance(self, user_id):
        self.create_account(user_id)
        return self.accounts[user_id]

    # ---------------------------
    # Pool management
    # ---------------------------
    def set_eligible(self, user_id, eligible=True):
        self.eligible[user_id] = eligible

    def add_to_pool(self, pool_name, user_id):
        self.create_account(user_id)
        if self.eligible[user_id]:
            self.pools[pool_name].add(user_id)

    def remove_from_pool(self, pool_name, user_id):
        if user_id in self.pools.get(pool_name, set()):
            self.pools[pool_name].remove(user_id)

    def list_pool(self, pool_name):
        return list(self.pools.get(pool_name, []))

    # ---------------------------
    # Epoch reward distribution
    # ---------------------------
    def distribute_epoch_rewards(self, epoch, reward_amount=10):
        """
        Distribute fixed rewards to one winner per pool.
        Selection is deterministic but rotates by epoch.
        """
        winners = {}
        for pool_name, users in self.pools.items():
            if users:
                users_list = sorted(list(users))  # deterministic order
                winner = users_list[epoch % len(users_list)]
                self.deposit(winner, reward_amount)
                winners[pool_name] = winner
            else:
                winners[pool_name] = None
        return winners

    # ---------------------------
    # Persistence
    # ---------------------------
    def snapshot(self):
        if self.persist_file:
            data = {
                "accounts": dict(self.accounts),
                "eligible": dict(self.eligible),
                "pools": {k: list(v) for k, v in self.pools.items()}
            }
            with open(self.persist_file, "w") as f:
                json.dump(data, f, indent=2)

    def load(self):
        if self.persist_file:
            try:
                with open(self.persist_file) as f:
                    data = json.load(f)
                    self.accounts = defaultdict(float, data.get("accounts", {}))
                    self.eligible = defaultdict(lambda: True, data.get("eligible", {}))
                    self.pools = defaultdict(set, {k: set(v) for k, v in data.get("pools", {}).items()})
            except FileNotFoundError:
                pass
