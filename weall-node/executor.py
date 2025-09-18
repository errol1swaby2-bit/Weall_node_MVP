import time
from collections import defaultdict
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

# -----------------------------
# Default PoH requirements
# -----------------------------
POH_REQUIREMENTS = {
    "propose": 3,
    "vote": 2,
    "post": 2,
    "comment": 2,
    "edit_post": 2,
    "delete_post": 2,
    "edit_comment": 2,
    "delete_comment": 2,
    "deposit": 1,
    "transfer": 1,
    "create_dispute": 3,
    "juror": 3,
    "mint_nft": 2
}


# -----------------------------
# Helper encryption utilities
# -----------------------------
def generate_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def encrypt_message(pub_key, message: str) -> bytes:
    return pub_key.encrypt(
        message.encode(),
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None)
    )


def decrypt_message(priv_key, ciphertext: bytes) -> str:
    return priv_key.decrypt(
        ciphertext,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(), label=None)
    ).decode()


class WeAllExecutor:
    def __init__(self, poh_requirements=None):
        self.poh_requirements = poh_requirements or {}
        self.current_epoch = 0
        self.state = {
            "users": {},          # user_id -> keys, PoH level, friends, groups, reputation
            "posts": {},          # post_id -> content
            "comments": {},       # comment_id -> content
            "proposals": {},      # proposal_id -> data
            "disputes": {},       # dispute_id -> data
            "treasury": defaultdict(float),
            "messages": defaultdict(list),
        }
        self.next_post_id = 1
        self.next_comment_id = 1
        self.next_proposal_id = 1
        self.next_dispute_id = 1

    # -----------------------------
    # PoH checks
    # -----------------------------
    def check_poh(self, user_id, action):
        required = self.poh_requirements.get(action, 1)
        user = self.state["users"].get(user_id)
        return user and user.get("poh_level", 0) >= required

    # -----------------------------
    # Reputation
    # -----------------------------
    def grant_reputation(self, user_id, amount):
        if user_id in self.state["users"]:
            self.state["users"][user_id]["reputation"] += amount

    def slash_reputation(self, user_id, amount):
        if user_id in self.state["users"]:
            self.state["users"][user_id]["reputation"] = max(
                0, self.state["users"][user_id]["reputation"] - amount
            )

    # -----------------------------
    # User management
    # -----------------------------
    def register_user(self, user_id, poh_level=1):
        if user_id in self.state["users"]:
            return {"ok": False, "error": "user_already_exists"}
        priv, pub = generate_keypair()
        self.state["users"][user_id] = {
            "private_key": priv,
            "public_key": pub,
            "poh_level": poh_level,
            "reputation": 0,
            "friends": [],
            "groups": [],
        }
        return {"ok": True}

    def add_friend(self, user_id, friend_id):
        if user_id not in self.state["users"] or friend_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        if friend_id not in self.state["users"][user_id]["friends"]:
            self.state["users"][user_id]["friends"].append(friend_id)
        return {"ok": True}

    def create_group(self, user_id, group_name, members=None):
        if user_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        self.state.setdefault("groups", {})
        if group_name in self.state["groups"]:
            return {"ok": False, "error": "group_already_exists"}
        members = members or [user_id]
        self.state["groups"][group_name] = members
        for m in members:
            self.state["users"][m]["groups"].append(group_name)
        return {"ok": True}

    # -----------------------------
    # Posts / Comments / Engagement
    # -----------------------------
    def create_post(self, user_id, content, tags=None, groups=None):
        if not self.check_poh(user_id, "post"):
            return {"ok": False, "error": "insufficient_poh"}
        pid = self.next_post_id
        self.next_post_id += 1
        self.state["posts"][pid] = {
            "post_id": pid,
            "user": user_id,
            "content": content,
            "tags": tags or [],
            "groups": groups or [],
            "comments": [],
            "likes": 0,
            "timestamp": time.time(),
        }
        self.grant_reputation(user_id, 2)
        return {"ok": True, "post_id": pid}

    def edit_post(self, user_id, post_id, new_content):
        post = self.state["posts"].get(post_id)
        if not post or post["user"] != user_id:
            return {"ok": False, "error": "unauthorized_or_post_missing"}
        post["content"] = new_content
        return {"ok": True}

    def delete_post(self, user_id, post_id):
        post = self.state["posts"].get(post_id)
        if not post or post["user"] != user_id:
            return {"ok": False, "error": "unauthorized_or_post_missing"}
        del self.state["posts"][post_id]
        self.slash_reputation(user_id, 2)
        return {"ok": True}

    def create_comment(self, user_id, post_id, content, tags=None):
        if not self.check_poh(user_id, "comment"):
            return {"ok": False, "error": "insufficient_poh"}
        if post_id not in self.state["posts"]:
            return {"ok": False, "error": "post_not_found"}
        cid = self.next_comment_id
        self.next_comment_id += 1
        self.state["comments"][cid] = {
            "comment_id": cid,
            "user": user_id,
            "post_id": post_id,
            "content": content,
            "tags": tags or [],
        }
        self.state["posts"][post_id]["comments"].append(cid)
        self.grant_reputation(user_id, 1)
        return {"ok": True, "comment_id": cid}

    def edit_comment(self, user_id, comment_id, new_content):
        comment = self.state["comments"].get(comment_id)
        if not comment or comment["user"] != user_id:
            return {"ok": False, "error": "unauthorized_or_comment_missing"}
        comment["content"] = new_content
        return {"ok": True}

    def delete_comment(self, user_id, comment_id):
        comment = self.state["comments"].get(comment_id)
        if not comment or comment["user"] != user_id:
            return {"ok": False, "error": "unauthorized_or_comment_missing"}
        post_id = comment["post_id"]
        self.state["posts"][post_id]["comments"].remove(comment_id)
        del self.state["comments"][comment_id]
        self.slash_reputation(user_id, 2)
        return {"ok": True}

    def like_post(self, user_id, post_id):
        post = self.state["posts"].get(post_id)
        if not post:
            return {"ok": False, "error": "post_not_found"}
        post["likes"] += 1
        return {"ok": True}

    # -----------------------------
    # Proposals / Governance
    # -----------------------------
    def propose(self, user_id, title, description, pallet_reference):
        if not self.check_poh(user_id, "propose"):
            return {"ok": False, "error": "insufficient_poh"}
        pid = self.next_proposal_id
        self.next_proposal_id += 1
        self.state["proposals"][pid] = {
            "proposal_id": pid,
            "creator": user_id,
            "title": title,
            "description": description,
            "pallet": pallet_reference,
            "votes": {},
            "status": "open",
        }
        return {"ok": True, "proposal_id": pid}

    def vote(self, user_id, proposal_id, vote_option, quorum=3):
        if not self.check_poh(user_id, "vote"):
            return {"ok": False, "error": "insufficient_poh"}
        proposal = self.state["proposals"].get(proposal_id)
        if not proposal:
            return {"ok": False, "error": "proposal_not_found"}
        if user_id in proposal["votes"]:
            return {"ok": False, "error": "already_voted"}
        proposal["votes"][user_id] = vote_option
        # Check quorum
        if len(proposal["votes"]) >= quorum:
            counts = defaultdict(int)
            for v in proposal["votes"].values():
                counts[v] += 1
            winner = max(counts, key=counts.get)
            proposal["status"] = f"enacted: {winner}"
            # Optionally allocate treasury if pallet == "Treasury"
            if proposal["pallet"] == "Treasury":
                self.allocate_treasury(winner, 100)
        return {"ok": True, "votes": proposal["votes"], "status": proposal["status"]}

    # -----------------------------
    # Disputes / Juror Voting
    # -----------------------------
    def create_dispute(self, reporter_id, target_post_id, description):
        if not self.check_poh(reporter_id, "dispute"):
            return {"ok": False, "error": "insufficient_poh"}
        did = self.next_dispute_id
        self.next_dispute_id += 1
        self.state["disputes"][did] = {
            "dispute_id": did,
            "reporter": reporter_id,
            "target_post": target_post_id,
            "description": description,
            "votes": {},
            "status": "open",
        }
        self.grant_reputation(reporter_id, 3)
        return {"ok": True, "dispute_id": did}

    def juror_vote(self, juror_id, dispute_id, vote_option, quorum=3):
        if not self.check_poh(juror_id, "juror"):
            return {"ok": False, "error": "insufficient_poh"}
        dispute = self.state["disputes"].get(dispute_id)
        if not dispute:
            return {"ok": False, "error": "dispute_not_found"}
        if juror_id in dispute["votes"]:
            return {"ok": False, "error": "already_voted"}
        dispute["votes"][juror_id] = vote_option
        self.grant_reputation(juror_id, 2)
        # Check quorum
        if len(dispute["votes"]) >= quorum:
            counts = defaultdict(int)
            for v in dispute["votes"].values():
                counts[v] += 1
            winner = max(counts, key=counts.get)
            dispute["status"] = f"resolved: {winner}"
        return {"ok": True, "votes": dispute["votes"], "status": dispute["status"]}

    # -----------------------------
    # Reporting convenience
    # -----------------------------
    def report_post(self, reporter_id, post_id, description):
        return self.create_dispute(reporter_id, post_id, description)

    def report_comment(self, reporter_id, comment_id, description):
        comment = self.state["comments"].get(comment_id)
        if not comment:
            return {"ok": False, "error": "comment_not_found"}
        return self.create_dispute(reporter_id, comment["post_id"], description)

    # -----------------------------
    # Treasury
    # -----------------------------
    def allocate_treasury(self, pool_name, amount):
        self.state["treasury"][pool_name] += amount
        return {"ok": True, "allocated_to": pool_name, "amount": amount}

    def reclaim_treasury(self, pool_name, amount):
        if self.state["treasury"].get(pool_name, 0) >= amount:
            self.state["treasury"][pool_name] -= amount
            return {"ok": True, "reclaimed_from": pool_name, "amount": amount}
        return {"ok": False, "error": "insufficient_funds"}

    # -----------------------------
    # NFT / PoH
    # -----------------------------
    def mint_nft(self, user_id, nft_id, metadata, level=1):
        if user_id not in self.state["users"]:
            return {"ok": False, "error": "user_not_registered"}
        # Assign PoH level if higher
        if level > self.state["users"][user_id]["poh_level"]:
            self.state["users"][user_id]["poh_level"] = level
        self.grant_reputation(user_id, 2)
        return {"ok": True, "nft_id": nft_id}

    # -----------------------------
    # Messaging
    # -----------------------------
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
