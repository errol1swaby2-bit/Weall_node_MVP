# weall_runtime/ledger.py
import json
import threading
import os
from collections import defaultdict
import hashlib

# ---------------------------
# Ledger
# ---------------------------
class Ledger:
    def __init__(self, persist_file=None):
        self.lock = threading.Lock()
        self.users = {}  # user_pub -> {"tier": int, "poh_status": str, "mint_cid": str}
        self.applications = {}  # app_id -> application data
        self.juror_votes = defaultdict(list)  # app_id -> list of votes
        self.blocks = []  # simple blockchain
        self.persist_file = persist_file
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

    def _save(self):
        if not self.persist_file:
            return
        data = {
            "users": self.users,
            "applications": self.applications,
            "juror_votes": dict(self.juror_votes),
            "blocks": self.blocks,
        }
        with open(self.persist_file, "w") as f:
            json.dump(data, f, indent=2)

# ---------------------------
# User management
# ---------------------------
    def register_user(self, user_pub, poh_cid=None, tier=None):
        with self.lock:
            if user_pub not in self.users:
                self.users[user_pub] = {
                    "tier": tier,
                    "poh_status": "pending",
                    "mint_cid": poh_cid
                }
                self._save()

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
    def add_juror_vote(self, app_id, juror_pub, vote, signature_b64):
        with self.lock:
            self.juror_votes[app_id].append({
                "juror_pub": juror_pub,
                "vote": vote,
                "signature_b64": signature_b64
            })
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
        """
        Add bytes to IPFS if available, else return pseudo-CID
        """
        try:
            from .storage import NodeStorage
            node_storage = NodeStorage()
            return node_storage.add_bytes(b)
        except Exception:
            return f"cid-{hashlib.sha256(b).hexdigest()[:16]}"

# ---------------------------
# Module-level singleton & aliases
# ---------------------------
_global_ledger = Ledger()

register_user = _global_ledger.register_user
create_application_record = _global_ledger.create_application_record
get_application = _global_ledger.get_application
set_application_status = _global_ledger.set_application_status
add_juror_vote = _global_ledger.add_juror_vote
get_juror_votes = _global_ledger.get_juror_votes
add_block = _global_ledger.add_block
add_bytes = _global_ledger.add_bytes
