import time
from collections import defaultdict
from typing import Optional

# For encryption
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

# IPFS client (optional, mock if IPFS not running)
try:
    import ipfshttpclient
except ImportError:
    ipfshttpclient = None


# ==========================
# Helper Encryption Utilities
# ==========================
def generate_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def encrypt_message(pub_key, message: str) -> bytes:
    return pub_key.encrypt(
        message.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(),
                     label=None)
    )


def decrypt_message(priv_key, ciphertext: bytes) -> str:
    return priv_key.decrypt(
        ciphertext,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(),
                     label=None)
    ).decode()


# ==========================
# Ledger
# ==========================
class WeCoinLedger:
    def __init__(self):
        self.accounts = defaultdict(float)
        self.pools = defaultdict(set)
        self.eligible = defaultdict(lambda: True)

    # Account operations
    def create_account(self, user_id):
        self.accounts.setdefault(user_id, 0.0)

    def deposit(self, user_id, amount):
        self.create_account(user_id)
        self.accounts[user_id] += amount

    def transfer(self, from_user, to_user, amount):
        if self.accounts[from_user] >= amount:
            self.accounts[from_user] -= amount
            self.deposit(to_user, amount)
            return True
        return False

    def balance(self, user_id):
        return self.accounts.get(user_id, 0.0)

    # Pools
    def add_to_pool(self, pool_name, user_id):
        if self.eligible.get(user_id, True):
            self.pools[pool_name].add(user_id)

    def remove_from_pool(self, pool_name, user_id):
        self.pools[pool_name].discard(user_id)

    def set_eligible(self, user_id, eligible=True):
        self.eligible[user_id] = eligible
        if not eligible:
            for pool in self.pools.values():
                pool.discard(user_id)

    def distribute_epoch_rewards(self, seed: int):
        winners = {}
        for pool_name, members in self.pools.items():
            if not members:
                continue
            idx = seed % len(members)
            member = list(members)[idx]
            if self.eligible[member]:
                reward = 10
                self.deposit(member, reward)
                winners[member] = reward
        return winners


# ==========================
# Main Executor
# ==========================
class WeAllExecutor:
    def __init__(self, dsl_file: str, poh_requirements: Optional[dict] = None):
        self.dsl_file = dsl_file
        self.ledger = WeCoinLedger()
        self.current_epoch = 0
        self.last_epoch_time = 0.0
        self.epoch_duration = 24 * 3600

        self.state = {
            "users": {},
            "posts": {},
            "comments": {},
            "disputes": {},
            "messages": defaultdict(list),
            "treasury": defaultdict(float),
        }

        self.next_post_id = 1
        self.next_comment_id = 1
        self.next_dispute_id = 1

        # Default PoH requirements if none provided
        self.poh_requirements = poh_requirements or {"propose": 2, "vote": 1}

        # IPFS connection with fallback
        if ipfshttpclient:
            try:
                self.ipfs = ipfshttpclient.connect()
            except Exception as e:
                print(f"[IPFS] connection failed: {e}")
                self.ipfs = None
        else:
            print("[IPFS] ipfshttpclient not installed, using mock")
            self.ipfs = None

    # -------------------
    # User management
    # -------------------
    def register_user(self, user_id, poh_level=1):
        if user_id in self.state["users"]:
            return {"ok": False, "error": "user_already_exists"}
        priv, pub = generate_keypair()
        self.state["users"][user_id] = {
            "poh_level": poh_level,
            "private_key": priv,
            "public_key": pub,
        }
        self.ledger.create_account(user_id)
        return {"ok": True}

    def set_user_eligible(self, user_id, eligible=True):
        self.ledger.set_eligible(user_id, eligible)

    def get_required_poh(self, action):
        return self.poh_requirements.get(action, 0)

    # -------------------
    # Posts
    # -------------------
    def _upload_to_ipfs(self, content: str) -> str:
        if not self.ipfs:
            return f"mock-{time.time()}"
        return self.ipfs.add_str(content)

    def create_post(self, user_id, content, tags=None, reward_amount=10):
        if user_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        ipfs_hash = self._upload_to_ipfs(content)
        post_id = self.next_post_id
        self.next_post_id += 1
        self.state["posts"][post_id] = {
            "user": user_id,
            "content_hash": ipfs_hash,
            "tags": tags or [],
            "comments": [],
        }
        self.ledger.deposit(user_id, reward_amount)
        self.ledger.add_to_pool("creators", user_id)
        return {"ok": True, "post_id": post_id, "ipfs_hash": ipfs_hash}

    # -------------------
    # Comments
    # -------------------
    def create_comment(self, user_id, post_id, content, tags=None, reward_amount=5):
        if user_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        if post_id not in self.state["posts"]:
            return {"ok": False, "error": "post_not_found"}
        ipfs_hash = self._upload_to_ipfs(content)
        cid = self.next_comment_id
        self.next_comment_id += 1
        self.state["comments"][cid] = {
            "user": user_id,
            "content_hash": ipfs_hash,
            "tags": tags or [],
            "post_id": post_id,
        }
        self.state["posts"][post_id]["comments"].append(cid)
        self.ledger.deposit(user_id, reward_amount)
        self.ledger.add_to_pool("creators", user_id)
        return {"ok": True, "comment_id": cid, "ipfs_hash": ipfs_hash}

    # -------------------
    # Disputes
    # -------------------
    def create_dispute(self, reporter_id, post_id, reason):
        if reporter_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        if post_id not in self.state["posts"]:
            return {"ok": False, "error": "post_not_found"}
        dispute_id = self.next_dispute_id
        self.next_dispute_id += 1
        self.state["disputes"][dispute_id] = {
            "reporter": reporter_id,
            "post_id": post_id,
            "reason": reason,
            "status": "open",
        }
        return {"ok": True, "dispute_id": dispute_id}

    # -------------------
    # Messaging
    # -------------------
    def send_message(self, from_user, to_user, message_text):
        if from_user not in self.state["users"] or to_user not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        pub = self.state["users"][to_user]["public_key"]
        encrypted = encrypt_message(pub, message_text)
        self.state["messages"][to_user].append({
            "from": from_user,
            "encrypted": encrypted,
            "timestamp": time.time()
        })
        return {"ok": True}

    def read_messages(self, user_id):
        if user_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        priv = self.state["users"][user_id]["private_key"]
        msgs = []
        for m in self.state["messages"][user_id]:
            try:
                text = decrypt_message(priv, m["encrypted"])
            except Exception:
                text = "[decryption_failed]"
            msgs.append({"from": m["from"], "text": text, "timestamp": m["timestamp"]})
        return msgs

    # -------------------
    # Epochs
    # -------------------
    def advance_epoch(self, force=False):
        now = time.time()
        if not force and now - self.last_epoch_time < self.epoch_duration:
            return {"ok": False, "error": "epoch_not_elapsed"}
        self.current_epoch += 1
        self.last_epoch_time = now
        winners = self.ledger.distribute_epoch_rewards(self.current_epoch)
        for uid in self.state["users"]:
            self.ledger.add_to_pool("creators", uid)
        return {"ok": True, "epoch": self.current_epoch, "winners": winners}
