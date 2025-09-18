import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# weall_runtime/ledger.py
import json
import threading
import hashlib
from collections import defaultdict
from app_state.ledger import Ledger as WeCoinLedger

# ---------------------------
# Ledger
# ---------------------------
class Ledger:
    def __init__(self, persist_file=None, cooldown_epochs=1):
        self.lock = threading.Lock()
        self.persist_file = persist_file
        self.cooldown_epochs = cooldown_epochs
        self.current_epoch = 0

        # -----------------------
        # Core data structures
        # -----------------------
        self.users = {}  # user_pub -> {"tier": int, "poh_status": str, "mint_cid": str}
        self.applications = {}  # app_id -> application data
        self.juror_votes = defaultdict(list)  # app_id -> list of votes
        self.blocks = []  # minimal blockchain

        # -----------------------
        # Token / reward ledger
        # -----------------------
        self.wecoin = WeCoinLedger()  # Pools, balances, eligibility

        # Track last participation per pool for cooldown logic
        self.last_participation = defaultdict(lambda: defaultdict(int))  # pool -> user_pub -> last_epoch

        self._load()

    # -------------------
    # Persistence helpers
    # -------------------
    def _load(self):
        if self.persist_file and os.path.exists(self.persist_file):
            with open(self.persist_file, "r") as f:
                data = json.load(f)
                self.users = data.get("users", {})
                self.applications = data.get("applications", {})
                self.juror_votes = defaultdict(list, {k: v for k, v in data.get("juror_votes", {}).items()})
                self.blocks = data.get("blocks", [])
                self.last_participation = defaultdict(lambda: defaultdict(int),
                                                     {k: defaultdict(int, v) for k, v in data.get("last_participation", {}).items()})

    def _save(self):
        if not self.persist_file:
            return
        data = {
            "users": self.users,
            "applications": self.applications,
            "juror_votes": dict(self.juror_votes),
            "blocks": self.blocks,
            "last_participation": {k: dict(v) for k, v in self.last_participation.items()},
        }
        with open(self.persist_file, "w") as f:
            json.dump(data, f, indent=2)

    # ---------------------------
    # User management
    # ---------------------------
    def register_user(self, user_pub, poh_cid=None, tier=None):
        with self.lock:
            if user_pub not in self.users:
                safe_tier = tier if isinstance(tier, int) and tier >= 0 else 0
                self.users[user_pub] = {
                    "tier": safe_tier,
                    "poh_status": "pending",
                    "mint_cid": poh_cid
                }
                # Initialize WeCoinLedger account
                self.wecoin.create_account(user_pub)
                self._update_pools_for_user(user_pub)
                self._save()

    # ---------------------------
    # Pool eligibility logic
    # ---------------------------
    def _eligible_for_pool(self, user_pub, pool_name):
        last_epoch = self.last_participation[pool_name].get(user_pub, -1)
        tier = self.users.get(user_pub, {}).get("tier") or 0
        if (self.current_epoch - last_epoch) >= self.cooldown_epochs and tier > 0:
            return True
        return False

    def _update_pools_for_user(self, user_pub):
        """
        Add user to pools if they are eligible based on tier and recent participation.
        """
        tier = self.users.get(user_pub, {}).get("tier") or 0
        if tier >= 1 and self._eligible_for_pool(user_pub, "creators"):
            self.wecoin.add_to_pool("creators", user_pub)
        if tier >= 2 and self._eligible_for_pool(user_pub, "jurors"):
            self.wecoin.add_to_pool("jurors", user_pub)
        if tier >= 3 and self._eligible_for_pool(user_pub, "operators"):
            self.wecoin.add_to_pool("operators", user_pub)

    # ---------------------------
    # Applications
    # ---------------------------
    def create_application_record(self, app_id, user_pub, tier_requested, video_cid=None, meta=None, jurors=None):
        with self.lock:
            self.applications[app_id] = {
                "app_id": app_id,
                "user_pub": user_pub,
                "tier_requested": tier_requested,
                "video_cid": video_cid,
                "meta": meta or {},
                "jurors": jurors or [],
                "status": "pending",
            }
            self._save()
            return self.applications[app_id]

    def get_application(self, app_id):
        return self.applications.get(app_id)

    def set_application_status(self, app_id, status, mint_cid=None):
        with self.lock:
            app = self.applications.get(app_id)
            if not app:
                return None
            app["status"] = status
            if mint_cid:
                app["mint_cid"] = mint_cid
                user_pub = app["user_pub"]
                if user_pub in self.users:
                    self.users[user_pub]["poh_status"] = status
                    self.users[user_pub]["mint_cid"] = mint_cid
            self._save()
            return app

    # ---------------------------
    # Juror votes
    # ---------------------------
    def add_juror_vote(self, app_id, juror_pub, vote, signature_b64, reward=5):
        with self.lock:
            self.juror_votes[app_id].append({
                "juror_pub": juror_pub,
                "vote": vote,
                "signature_b64": signature_b64
            })
            # Reward juror in WeCoinLedger
            self.wecoin.deposit(juror_pub, reward)
            self._save()

    def get_juror_votes(self, app_id):
        return self.juror_votes.get(app_id, [])

    # ---------------------------
    # Minimal blockchain
    # ---------------------------
    def add_block(self, block_hash, prev_hash, payload):
        with self.lock:
            self.blocks.append({
                "hash": block_hash,
                "prev_hash": prev_hash,
                "payload": payload
            })
            self._save()

    # ---------------------------
    # Minimal IPFS fallback
    # ---------------------------
    def add_bytes(self, b: bytes):
        try:
            from .storage import NodeStorage
            node_storage = NodeStorage()
            return node_storage.add_bytes(b)
        except Exception:
            return f"cid-{hashlib.sha256(b).hexdigest()[:16]}"

    # ---------------------------
    # Epoch handling
    # ---------------------------
    def advance_epoch(self):
        """
        Advance epoch and distribute rewards to eligible users in each pool.
        """
        with self.lock:
            self.current_epoch += 1

            # Update pools based on dynamic eligibility
            for user_pub in self.users.keys():
                self._update_pools_for_user(user_pub)

            # Distribute rewards via WeCoinLedger
            winners = self.wecoin.distribute_epoch_rewards(self.current_epoch)

            # Record last participation
            for pool_name, winner in winners.items():
                if winner:
                    self.last_participation[pool_name][winner] = self.current_epoch

            self._save()
            return winners

    # ---------------------------
    # User eligibility
    # ---------------------------
    def set_user_eligible(self, user_pub, eligible=True):
        with self.lock:
            self.wecoin.set_eligible(user_pub, eligible)

# ---------------------------
# Module-level singleton & aliases
# ---------------------------
_global_ledger = Ledger(persist_file="ledger_data.json", cooldown_epochs=1)

register_user = _global_ledger.register_user
create_application_record = _global_ledger.create_application_record
get_application = _global_ledger.get_application
set_application_status = _global_ledger.set_application_status
add_juror_vote = _global_ledger.add_juror_vote
get_juror_votes = _global_ledger.get_juror_votes
add_block = _global_ledger.add_block
add_bytes = _global_ledger.add_bytes
advance_epoch = _global_ledger.advance_epoch
set_user_eligible = _global_ledger.set_user_eligible
