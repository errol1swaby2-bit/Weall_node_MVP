# app_state/ledger.py
from collections import defaultdict

class Ledger:
    def __init__(self, persist_file=None):
        self.accounts = defaultdict(float)
        self.persist_file = persist_file  # optional, for snapshotting
        self.pools = defaultdict(set)

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

    def snapshot(self):
        # Optionally save state to persist_file
        if self.persist_file:
            import json
            with open(self.persist_file, "w") as f:
                json.dump(self.accounts, f)

    def load(self):
        if self.persist_file:
            import json
            try:
                with open(self.persist_file) as f:
                    self.accounts = defaultdict(float, json.load(f))
            except FileNotFoundError:
                pass
