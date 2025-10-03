@@
     def add_allowed_user(self, post_id: int, user_id: str):
         """Uploader grants explicit access to 'user_id' for a private post."""
         post = self.state["posts"].get(post_id)
-        if not post:
-            return False
-        post.setdefault("allowed_users", []).append(user_id)
-        return True
        if not post:
            return False
        post.setdefault("allowed_users", []).append(user_id)
        return True
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
# ==============================
# weall_cli.py (Updated)
# ==============================
from executor import WeAllExecutor, POH_REQUIREMENTS

def safe_int_input(prompt):
    try:
        return int(input(prompt))
    except ValueError:
        print("Invalid input, expected a number.")
        return None

def run_cli():
    executor = WeAllExecutor(poh_requirements=POH_REQUIREMENTS)
    print("WeAll CLI started. Type 'exit' to quit.")

    while True:
        cmd = input(
            "\nCommand (register/propose/vote/post/comment/edit_post/delete_post/edit_comment/delete_comment/"
            "list_user_posts/list_tag_posts/show_post/show_posts/report_post/report_comment/"
            "create_dispute/juror_vote/like_post/deposit/transfer/balance/allocate_treasury/reclaim_treasury/"
            "send_message/read_messages/exit): "
        ).strip().lower()

        if cmd == "exit":
            break

        # ------------------------
        # User Management
        # ------------------------
        elif cmd == "register":
            user = input("User ID: ")
            poh = safe_int_input("PoH Level: ")
            result = executor.register_user(user, poh_level=poh)
            print(result)

        elif cmd == "add_friend":
            uid = input("User ID: ")
            fid = input("Friend ID: ")
            print(executor.add_friend(uid, fid))

        elif cmd == "create_group":
            uid = input("User ID: ")
            group_name = input("Group name: ")
            members = input("Member IDs (comma-separated, optional): ")
            member_list = members.split(",") if members else None
            print(executor.create_group(uid, group_name, member_list))

        # ------------------------
        # Posts / Comments
        # ------------------------
        elif cmd == "post":
            uid = input("User ID: ")
            content = input("Post content: ")
            tags = input("Tags (comma-separated, optional): ").split(",") if input("Add tags? (y/n): ").lower() == "y" else None
            print(executor.create_post(uid, content, tags))

        elif cmd == "comment":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            content = input("Comment content: ")
            tags = input("Tags (comma-separated, optional): ").split(",") if input("Add tags? (y/n): ").lower() == "y" else None
            print(executor.create_comment(uid, pid, content, tags))

        elif cmd == "edit_post":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            new_content = input("New post content: ")
            print(executor.edit_post(uid, pid, new_content))

        elif cmd == "delete_post":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            print(executor.delete_post(uid, pid))

        elif cmd == "edit_comment":
            uid = input("User ID: ")
            cid = safe_int_input("Comment ID: ")
            new_content = input("New comment content: ")
            print(executor.edit_comment(uid, cid, new_content))

        elif cmd == "delete_comment":
            uid = input("User ID: ")
            cid = safe_int_input("Comment ID: ")
            print(executor.delete_comment(uid, cid))

        elif cmd == "like_post":
            uid = input("User ID: ")
            pid = safe_int_input("Post ID: ")
            print(executor.like_post(uid, pid))

        # ------------------------
        # Governance / Proposals
        # ------------------------
        elif cmd == "propose":
            uid = input("User ID: ")
            title = input("Proposal title: ")
            desc = input("Proposal description: ")
            pallet = input("Pallet reference: ")
            print(executor.propose(uid, title, desc, pallet))

        elif cmd == "vote":
            uid = input("User ID: ")
            pid = safe_int_input("Proposal ID: ")
            option = input("Vote option: ")
            print(executor.vote(uid, pid, option))

        # ------------------------
        # Disputes / Juror Voting
        # ------------------------
        elif cmd == "create_dispute":
            uid = input("Reporter ID: ")
            pid = safe_int_input("Target Post ID: ")
            desc = input("Dispute description: ")
            print(executor.create_dispute(uid, pid, desc))

        elif cmd == "juror_vote":
            uid = input("Juror ID: ")
            did = safe_int_input("Dispute ID: ")
            vote_option = input("Vote option: ")
            print(executor.juror_vote(uid, did, vote_option))

        elif cmd == "report_post":
            uid = input("Reporter ID: ")
            pid = safe_int_input("Post ID: ")
            desc = input("Report description: ")
            print(executor.report_post(uid, pid, desc))

        elif cmd == "report_comment":
            uid = input("Reporter ID: ")
            cid = safe_int_input("Comment ID: ")
            desc = input("Report description: ")
            print(executor.report_comment(uid, cid, desc))

        # ------------------------
        # Treasury
        # ------------------------
        elif cmd == "allocate_treasury":
            pool = input("Pool name: ")
            amt = safe_int_input("Amount: ")
            print(executor.allocate_treasury(pool, amt))

        elif cmd == "reclaim_treasury":
            pool = input("Pool name: ")
            amt = safe_int_input("Amount: ")
            print(executor.reclaim_treasury(pool, amt))

        # ------------------------
        # Ledger / Transfers
        # ------------------------
        elif cmd == "deposit":
            uid = input("User ID: ")
            amt = safe_int_input("Amount: ")
            executor.state["treasury"][uid] += amt
            print(f"{amt} deposited to {uid}'s treasury account")

        elif cmd == "transfer":
            from_user = input("From user: ")
            to_user = input("To user: ")
            amt = safe_int_input("Amount: ")
            # Simplified; add more ledger logic if needed
            if executor.state["treasury"].get(from_user, 0) >= amt:
                executor.state["treasury"][from_user] -= amt
                executor.state["treasury"][to_user] += amt
                print("Transfer successful")
            else:
                print("Transfer failed")

        elif cmd == "balance":
            uid = input("User ID: ")
            bal = executor.state["treasury"].get(uid, 0)
            print(f"{uid} balance: {bal}")

        # ------------------------
        # Messaging
        # ------------------------
        elif cmd == "send_message":
            sender = input("From user: ")
            recipient = input("To user: ")
            msg = input("Message text: ")
            print(executor.send_message(sender, recipient, msg))

        elif cmd == "read_messages":
            uid = input("User ID: ")
            msgs = executor.read_messages(uid)
            for m in msgs:
                print(f"From {m['from']} | {m['timestamp']}: {m['text']}")

        # ------------------------
        # Posts / Display
        # ------------------------
        elif cmd == "list_user_posts":
            uid = input("User ID: ")
            posts = [pid for pid, p in executor.state["posts"].items() if p["user"] == uid]
            print(f"Posts by {uid}: {posts}")

        elif cmd == "list_tag_posts":
            tag = input("Tag to search: ")
            posts = [pid for pid, p in executor.state["posts"].items() if tag in p.get("tags", [])]
            print(f"Posts with tag '{tag}': {posts}")

        elif cmd == "show_post":
            pid = safe_int_input("Post ID: ")
            post = executor.state["posts"].get(pid)
            print(post if post else f"Post {pid} not found.")

        elif cmd == "show_posts":
            for pid, post in executor.state["posts"].items():
                print(f"{pid}: {post}")

        else:
            print("Unknown command.")


if __name__ == "__main__":
    run_cli()
#!/usr/bin/env python3
"""
Production-ready-ish WeAll API (Termux-friendly).
Includes:
- API key authentication (X-API-KEY or Authorization: Bearer)
- CORS + basic security headers
- Upload size guard & cleanup
- In-memory rate limiting
- Background replication worker (pin only, no key sharing)
"""
import os, json, time, logging, base64, subprocess, threading
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from executor import WeAllExecutor

# -------- Config --------
MAX_UPLOAD_SIZE = int(os.environ.get("WEALL_MAX_UPLOAD_SIZE_BYTES", str(50 * 1024 * 1024)))
ALLOWED_ORIGINS = os.environ.get("WEALL_ALLOWED_ORIGINS", "*")
REPLICATION_K = int(os.environ.get("WEALL_REPLICATION_K", "3"))
API_KEY = os.environ.get("WEALL_API_KEY", "dev-local-api-key")
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# -------- Logging --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("weall")

# -------- Init --------
POH_REQUIREMENTS = getattr(__import__("executor"), "POH_REQUIREMENTS", {})
executor = WeAllExecutor(poh_requirements=POH_REQUIREMENTS)
executor.state.setdefault("nodes", {})
executor.state.setdefault("posts", {})
executor.state.setdefault("replications", [])

app = FastAPI(title="WeAll Node API (prod-ready)")

# -------- CORS --------
origins = ["*"] if ALLOWED_ORIGINS == "*" else [o.strip() for o in ALLOWED_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- Rate limiting --------
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = int(os.environ.get("WEALL_RATE_LIMIT_MAX", "60"))
_rate_state = {}

def rate_limited(key: str):
    now = int(time.time())
    ws, cnt = _rate_state.get(key, (now, 0))
    if now - ws >= RATE_LIMIT_WINDOW:
        ws, cnt = now, 0
    cnt += 1
    _rate_state[key] = (ws, cnt)
    return cnt > RATE_LIMIT_MAX

# -------- Auth --------
def get_api_key_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip()
    api = request.headers.get("x-api-key")
    if api:
        return api.strip()
    return None

def require_api_key(request: Request):
    key = get_api_key_from_request(request)
    client_ip = request.client.host if request.client else "unknown"
    rate_key = key or client_ip
    if rate_limited(rate_key):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid_api_key")
    return key

# -------- Replication worker --------
def _replication_worker():
    while True:
        try:
            jobs = list(executor.state.get("replications", []))
            for job in jobs:
                if job.get("status") != "requested":
                    continue
                cid, post_id, peers = job.get("cid"), job.get("post_id"), job.get("peers", [])
                for peer in peers:
                    try:
                        node = executor.state.get("nodes", {}).get(peer, {})
                        url = node.get("api_url")
                        if not url:
                            executor.record_replication_status(peer, post_id, "no_api_url")
                            continue
                        try:
                            import requests
                            r = requests.post(f"{url.rstrip('/')}/replicate_pin",
                                              json={"cid": cid, "post_id": post_id}, timeout=10)
                            if r.status_code == 200:
                                executor.record_replication_status(peer, post_id, "pushed")
                            else:
                                executor.record_replication_status(peer, post_id, f"peer_err_{r.status_code}")
                        except Exception as re:
                            executor.record_replication_status(peer, post_id, f"push_err:{str(re)[:200]}")
                    except Exception as e:
                        executor.record_replication_status(peer, post_id, f"failed:{str(e)[:200]}")
                job["status"] = "pushed"
        except Exception as e:
            log.exception("replication worker error: %s", e)
        time.sleep(5)

threading.Thread(target=_replication_worker, daemon=True).start()

# -------- Utils --------
def _remove_file_silent(path): 
    try: os.remove(path)
    except: pass

def _ensure_upload_within_limits(fileobj):
    try:
        if hasattr(fileobj, "file") and hasattr(fileobj.file, "seek"):
            cur = fileobj.file.tell()
            fileobj.file.seek(0, os.SEEK_END)
            size = fileobj.file.tell()
            fileobj.file.seek(cur)
            if size > MAX_UPLOAD_SIZE:
                raise HTTPException(status_code=413, detail="file_too_large")
    except HTTPException: raise
    except: pass

# -------- API Endpoints --------
@app.post("/register_pubkey")
async def register_pubkey(request: Request):
    require_api_key(request)
    body = await request.json()
    user_id, pubkey_pem = body.get("user_id"), body.get("pubkey_pem")
    api_url = body.get("api_url")
    if not user_id or not pubkey_pem:
        raise HTTPException(status_code=400, detail="missing_user_or_pubkey")
    node = executor.state["nodes"].setdefault(user_id, {})
    node["pubkey"] = pubkey_pem
    if api_url: node["api_url"] = api_url
    node["pubkey_registered_at"] = time.time()
    return {"status": "ok", "user_id": user_id}

@app.post("/get_recipients_pubkeys")
async def get_recipients_pubkeys(request: Request):
    require_api_key(request)
    body = await request.json()
    user_id, groups, visibility = body.get("user_id"), body.get("groups") or [], body.get("visibility", "private")
    recipients = []
    uploader = executor.state.get("nodes", {}).get(user_id)
    if uploader and uploader.get("pubkey"):
        recipients.append({"id": user_id, "pubkey_pem": uploader["pubkey"]})
    if visibility == "group":
        for g in groups:
            for m in executor.get_group_peers(g) or []:
                if m != user_id:
                    minfo = executor.state.get("nodes", {}).get(m, {})
                    if minfo.get("pubkey"):
                        recipients.append({"id": m, "pubkey_pem": minfo["pubkey"]})
    return JSONResponse({"recipients": recipients})

@app.post("/post_encrypted_e2e")
async def post_encrypted_e2e(request: Request,
    user_id: str = Form(...), content: str = Form(""), iv_b64: str = Form(...),
    wrapped_keys: str = Form(...), visibility: str = Form("private"),
    groups: Optional[str] = Form(None), file: UploadFile = File(...)):
    require_api_key(request)
    _ensure_upload_within_limits(file)
    saved_path = None
    try:
        ts = int(time.time())
        safe_name = f"{ts}_{file.filename}"
        saved_path = os.path.join(UPLOADS_DIR, safe_name)
        with open(saved_path, "wb") as fh: fh.write(await file.read())
        cid = subprocess.check_output(["ipfs", "add", "-Q", saved_path]).decode().strip()
        subprocess.check_output(["ipfs", "pin", "add", cid])
        group_list = groups.split(",") if groups else None
        post_id = executor.create_post(user_id=user_id,
            content=(content + f"\n\n[CID:{cid}]"), tags=None, groups=group_list)
        post = executor.state["posts"][post_id]
        post.update({"cid": cid, "visibility": visibility,
                     "groups": group_list or [], "iv_b64": iv_b64})
        try:
            wlist = json.loads(wrapped_keys)
            post["wrapped_keys"] = {w["recipient_id"]: w["wrapped_key_b64"] for w in wlist}
        except: post["wrapped_keys"] = {}
        replication_peers = set()
        if group_list:
            for g in group_list:
                replication_peers.update(executor.pick_replication_peers(g, k=REPLICATION_K))
        job = {"post_id": post_id, "cid": cid, "peers": list(replication_peers),
               "status": "requested", "created_at": time.time()}
        executor.state["replications"].append(job)
        for p in replication_peers: executor.record_replication_status(p, post_id, "requested")
        _remove_file_silent(saved_path)
        return {"status": "ok", "post_id": post_id, "cid": cid}
    except Exception as e:
        if saved_path: _remove_file_silent(saved_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ipfs_raw/{cid}")
async def ipfs_raw(cid: str, request: Request):
    try:
        proc = subprocess.Popen(["ipfs", "cat", cid], stdout=subprocess.PIPE)
        return StreamingResponse(proc.stdout, media_type="application/octet-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
# app_state/node.py
class Node:
    def __init__(self, ledger):
        self.ledger = ledger
        self.peers = []

    def register_peer(self, peer_id):
        if peer_id not in self.peers:
            self.peers.append(peer_id)
        return self.peers
# app_state/governance.py

proposals = {}
proposal_counter = 1
votes = {}

def propose(user_id: str, title: str, description: str):
    global proposal_counter
    pid = proposal_counter
    proposals[pid] = {
        "user": user_id,
        "title": title,
        "description": description,
        "votes": 0
    }
    proposal_counter += 1
    return {"ok": True, "proposal_id": pid}

def vote(user_id: str, proposal_id: int, approve: bool):
    if proposal_id not in proposals:
        return {"ok": False, "error": "proposal_not_found"}
    votes.setdefault(proposal_id, {})
    votes[proposal_id][user_id] = approve
    # Count votes
    total = sum(1 if v else -1 for v in votes[proposal_id].values())
    proposals[proposal_id]["votes"] = total
    return {"ok": True, "votes": total}
# api/ledger.py

from fastapi import APIRouter

router = APIRouter(
    prefix="/ledger",
    tags=["Ledger"]
)

# In-memory placeholder ledger
ledger_state = {
    "accounts": {},
    "balances": {},
}

# ------------------------
# Endpoints
# ------------------------

@router.get("/")
def get_ledger_status():
    """
    Basic health/status endpoint for the ledger module
    """
    return {"status": "ok", "message": "Ledger module is active"}


@router.post("/create_account/{user_id}")
def create_account(user_id: str):
    """
    Create a new account with zero balance
    """
    if user_id in ledger_state["accounts"]:
        return {"ok": False, "error": "account_already_exists"}
    
    ledger_state["accounts"][user_id] = 0
    ledger_state["balances"][user_id] = 0
    return {"ok": True, "user_id": user_id}


@router.get("/balance/{user_id}")
def get_balance(user_id: str):
    """
    Get the balance of a user account
    """
    if user_id not in ledger_state["balances"]:
        return {"ok": False, "error": "account_not_found"}
    return {"ok": True, "balance": ledger_state["balances"][user_id]}


@router.post("/deposit/{user_id}/{amount}")
def deposit(user_id: str, amount: float):
    """
    Deposit an amount into a user account
    """
    if user_id not in ledger_state["balances"]:
        return {"ok": False, "error": "account_not_found"}
    
    ledger_state["balances"][user_id] += amount
    return {"ok": True, "balance": ledger_state["balances"][user_id]}


@router.post("/transfer/{from_user}/{to_user}/{amount}")
def transfer(from_user: str, to_user: str, amount: float):
    """
    Transfer funds from one account to another
    """
    if from_user not in ledger_state["balances"]:
        return {"ok": False, "error": "from_account_not_found"}
    if to_user not in ledger_state["balances"]:
        return {"ok": False, "error": "to_account_not_found"}
    if ledger_state["balances"][from_user] < amount:
        return {"ok": False, "error": "insufficient_funds"}
    
    ledger_state["balances"][from_user] -= amount
    ledger_state["balances"][to_user] += amount
    return {"ok": True, "from_balance": ledger_state["balances"][from_user], "to_balance": ledger_state["balances"][to_user]}
# api/reputation.py
from fastapi import APIRouter

router = APIRouter(prefix="/reputation", tags=["Reputation"])

reputation_scores = {}

@router.post("/grant/{user_id}/{amount}")
def grant(user_id: str, amount: int):
    reputation_scores[user_id] = reputation_scores.get(user_id, 0) + amount
    return {"ok": True, "reputation": reputation_scores[user_id]}

@router.post("/slash/{user_id}/{amount}")
def slash(user_id: str, amount: int):
    reputation_scores[user_id] = reputation_scores.get(user_id, 0) - amount
    return {"ok": True, "reputation": reputation_scores[user_id]}
# api/messaging.py
from fastapi import APIRouter

router = APIRouter(prefix="/messaging", tags=["Messaging"])

messages = {}

@router.post("/send/{from_user}/{to_user}")
def send(from_user: str, to_user: str, message: str):
    messages.setdefault(to_user, []).append({"from": from_user, "text": message})
    return {"ok": True}

@router.get("/inbox/{user_id}")
def inbox(user_id: str):
    return {"messages": messages.get(user_id, [])}
# api/treasury.py
from fastapi import APIRouter
from api.ledger import ledger_state

router = APIRouter(prefix="/treasury", tags=["Treasury"])

treasury_state = {
    "funds": 0
}

@router.get("/")
def status():
    return {"status": "ok", "funds": treasury_state["funds"]}

@router.post("/deposit/{user_id}/{amount}")
def deposit(user_id: str, amount: float):
    if user_id not in ledger_state["balances"]:
        return {"ok": False, "error": "user_not_found"}
    treasury_state["funds"] += amount
    ledger_state["balances"][user_id] -= amount
    return {"ok": True, "treasury_funds": treasury_state["funds"]}
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app_state import poh

router = APIRouter(
    prefix="/poh",
    tags=["Proof of Humanity"]
)

class ApplyTier2(BaseModel):
    user: str
    evidence: str

class VerifyTier2(BaseModel):
    user: str
    approver: str
    approve: bool

class VerifyTier3(BaseModel):
    user: str
    video_proof: str

@router.post("/tier1/{user}")
def verify_tier1(user: str):
    return poh.verify_tier1(user)

@router.post("/tier2/apply")
def apply_tier2(data: ApplyTier2):
    return poh.apply_tier2(data.user, data.evidence)

@router.post("/tier2/verify")
def verify_tier2(data: VerifyTier2):
    return poh.verify_tier2(data.user, data.approver, data.approve)

@router.post("/tier3/verify")
def verify_tier3(data: VerifyTier3):
    return poh.verify_tier3(data.user, data.video_proof)

@router.get("/status/{user}")
def get_status(user: str):
    return poh.status(user)

# weall_runtime/crypto_utils.py
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

def verify_ed25519_sig(pub_b64: str, message: bytes, sig_b64: str) -> bool:
    """
    Verify Ed25519 signature. pub_b64 and sig_b64 are base64 strings.
    """
    try:
        pub = base64.b64decode(pub_b64)
        sig = base64.b64decode(sig_b64)
        pk = ed25519.Ed25519PublicKey.from_public_bytes(pub)
        pk.verify(sig, message)
        return True
    except Exception:
        return False
# weall_runtime/governance.py
"""
Simplified governance system for WeAll.
- 1 identity = 1 vote
- Simple majority wins
- No quadratic voting, no stability weighting
- Supports proposal creation, voting, closing, and optional enactment

Dependencies:
- A storage client (e.g. weall_runtime.storage.IPFSClient) for description storage.
- A ledger-like object if actions require transfers (optional).
"""

import time
import uuid
import threading
from typing import Dict, Any, Optional, List


class ProposalStatus:
    OPEN = "open"
    CLOSED = "closed"
    EXECUTED = "executed"
    REJECTED = "rejected"


class GovernanceError(Exception):
    pass


class Proposal:
    def __init__(self, proposer: str, title: str, description_cid: str, action: Dict[str, Any], duration_seconds: int):
        self.id = str(uuid.uuid4())
        self.proposer = proposer
        self.title = title
        self.description_cid = description_cid
        self.action = action
        self.created_at = int(time.time())
        self.expires_at = self.created_at + duration_seconds
        self.status = ProposalStatus.OPEN

        # votes: {"yes": set(user_ids), "no": set(user_ids)}
        self.votes = {"yes": set(), "no": set()}
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        return self.status == ProposalStatus.OPEN and int(time.time()) < self.expires_at

    def add_vote(self, user_id: str, choice: str) -> None:
        if not self.is_open():
            raise GovernanceError("proposal_closed_or_expired")
        choice = choice.lower()
        if choice not in ("yes", "no"):
            raise GovernanceError("invalid_choice")

        with self._lock:
            # remove from both tallies in case user changes vote
            self.votes["yes"].discard(user_id)
            self.votes["no"].discard(user_id)
            self.votes[choice].add(user_id)


class Governance:
    def __init__(self, storage_client, ledger: Optional[object] = None, quorum_fraction: float = 0.0):
        """
        storage_client: expects add_str(content)->cid, get_str(cid)->content
        ledger: optional, used for proposals that transfer funds
        quorum_fraction: optional, fraction of eligible voters required
        """
        self._storage = storage_client
        self._ledger = ledger
        self._proposals: Dict[str, Proposal] = {}
        self._lock = threading.Lock()
        self._quorum_fraction = float(quorum_fraction)

    # --------------------------
    # Proposal lifecycle
    # --------------------------
    def propose(self, proposer_id: str, title: str, description_text: str, action: Optional[Dict[str, Any]] = None, duration_seconds: int = 7 * 24 * 3600) -> str:
        cid = self._storage.add_str(description_text)
        prop = Proposal(proposer_id, title, cid, action or {}, duration_seconds)
        with self._lock:
            self._proposals[prop.id] = prop
        return prop.id

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        with self._lock:
            return self._proposals.get(proposal_id)

    def list_proposals(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": p.id,
                    "title": p.title,
                    "proposer": p.proposer,
                    "status": p.status,
                    "created_at": p.created_at,
                    "expires_at": p.expires_at,
                    "votes_yes": len(p.votes["yes"]),
                    "votes_no": len(p.votes["no"]),
                }
                for p in self._proposals.values()
            ]

    # --------------------------
    # Voting
    # --------------------------
    def vote(self, voter_id: str, proposal_id: str, choice: str) -> None:
        prop = self.get_proposal(proposal_id)
        if not prop:
            raise GovernanceError("proposal_not_found")
        prop.add_vote(voter_id, choice)

    # --------------------------
    # Tallying
    # --------------------------
    def tally(self, proposal_id: str) -> Dict[str, Any]:
        prop = self.get_proposal(proposal_id)
        if not prop:
            raise GovernanceError("proposal_not_found")

        yes = len(prop.votes["yes"])
        no = len(prop.votes["no"])
        total = yes + no

        passes_quorum = True
        if self._quorum_fraction > 0:
            # approximate eligible = yes+no voters for simplicity
            eligible_sum = max(total, 1)
            passes_quorum = (total / eligible_sum) >= self._quorum_fraction

        outcome = "tie"
        if yes > no:
            outcome = "passed"
        elif no > yes:
            outcome = "rejected"

        return {
            "yes": yes,
            "no": no,
            "total_votes": total,
            "passes_quorum": passes_quorum,
            "outcome": outcome,
        }

    # --------------------------
    # Enactment
    # --------------------------
    def enact(self, proposal_id: str) -> Dict[str, Any]:
        prop = self.get_proposal(proposal_id)
        if not prop:
            raise GovernanceError("proposal_not_found")

        tally = self.tally(proposal_id)
        if not tally["passes_quorum"]:
            prop.status = ProposalStatus.REJECTED
            return {"ok": False, "reason": "no_quorum", "tally": tally}

        if tally["outcome"] != "passed":
            prop.status = ProposalStatus.REJECTED
            return {"ok": False, "reason": "not_approved", "tally": tally}

        # handle action if present
        action = prop.action
        try:
            if action and action.get("type") == "transfer" and self._ledger:
                from_id = action.get("from")
                to_id = action.get("to")
                amount = float(action.get("amount", 0.0))
                ok = False
                if from_id and to_id and amount > 0:
                    ok = self._ledger.transfer(from_id, to_id, amount)
                if not ok:
                    prop.status = ProposalStatus.REJECTED
                    return {"ok": False, "reason": "transfer_failed", "tally": tally}

            prop.status = ProposalStatus.EXECUTED
            return {"ok": True, "tally": tally}
        except Exception as e:
            prop.status = ProposalStatus.REJECTED
            return {"ok": False, "reason": str(e), "tally": tally}
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
# weall_runtime/poh.py
import uuid
import json
import hashlib
from datetime import datetime
from .ledger import (
    create_application_record,
    get_application,
    set_application_status,
    add_juror_vote,
    get_juror_votes,
    add_block,
    register_user,
)
from .utils import choose_jurors_for_application, simple_threshold_check
from .crypto_utils import verify_ed25519_sig

# Configurable thresholds
DEFAULT_JUROR_COUNT = 10
DEFAULT_APPROVAL_THRESHOLD = 7  # need >=7 approvals

# ---------------------------
# Tier 1: Basic onboarding
# ---------------------------
def apply_tier1(user_pub: str, email_hash: str):
    """
    Tier1 onboarding: minimal KYC (hashed email)
    """
    register_user(user_pub, poh_cid=None, tier=1)
    payload = {
        "type": "poh_tier1",
        "user_pub": user_pub,
        "email_hash": email_hash,
        "issued_at": datetime.utcnow().isoformat()
    }
    bh = hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()
    add_block(bh, "0", payload)
    return {"ok": True, "user_pub": user_pub, "tier": 1}

# ---------------------------
# Tier 2: Asynchronous video verification
# ---------------------------
def apply_tier2(user_pub: str, video_cid: str, meta: dict, node):
    """
    Create a Tier2 application: persist application and deterministically choose jurors.
    """
    app_id = str(uuid.uuid4())
    jurors = choose_jurors_for_application(node, count=DEFAULT_JUROR_COUNT)
    create_application_record(app_id, user_pub, tier_requested=2, video_cid=video_cid, meta=meta, jurors=jurors)

    payload = {
        "type": "poh_application_created",
        "app_id": app_id,
        "user_pub": user_pub,
        "tier": 2,
        "jurors": jurors,
        "video_cid": video_cid,
        "meta": meta
    }
    last_hash = node.get_last_block_hashes(1)[0] if node.get_last_block_hashes(1) else "0"
    add_block(hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(), last_hash, payload)
    return {"app_id": app_id, "jurors": jurors}

def juror_submit_vote(app_id: str, juror_pub: str, vote: str, signature_b64: str):
    """
    Called when a juror submits a vote. Verify signature then persist.
    """
    msg = f"{app_id}:{vote}".encode("utf-8")
    if not verify_ed25519_sig(juror_pub, msg, signature_b64):
        return {"ok": False, "reason": "invalid_signature"}

    add_juror_vote(app_id, juror_pub, vote, signature_b64)
    votes_list = [v["vote"] for v in get_juror_votes(app_id)]

    if simple_threshold_check(votes_list, threshold=DEFAULT_APPROVAL_THRESHOLD):
        # Mint Tier2 PoH NFT
        app = get_application(app_id)
        cid = add_bytes(json.dumps({"user_pub": app.user_pub, "tier": 2, "app_id": app_id}).encode("utf-8"))
        set_application_status(app_id, "approved", mint_cid=cid)

        payload = {"type": "poh_minted", "app_id": app_id, "tier": 2, "cid": cid}
        add_block(hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(), "0", payload)
        return {"ok": True, "finalized": True, "cid": cid}

    return {"ok": True, "finalized": False}

# ---------------------------
# Tier 3: Live video + governance
# ---------------------------
def apply_tier3(user_pub: str, requested_window: dict, node):
    """
    requested_window: {"from": iso_ts, "to": iso_ts}
    Returns scheduling token + jurors assigned
    """
    app_id = str(uuid.uuid4())
    jurors = choose_jurors_for_application(node, count=DEFAULT_JUROR_COUNT)
    create_application_record(app_id, user_pub, tier_requested=3, meta={"requested_window": requested_window}, jurors=jurors)

    payload = {"type": "poh_tier3_request", "app_id": app_id, "user_pub": user_pub, "jurors": jurors}
    last_hash = node.get_last_block_hashes(1)[0] if node.get_last_block_hashes(1) else "0"
    add_block(hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest(), last_hash, payload)

    # In production: notify jurors, schedule WebRTC live call
    return {"app_id": app_id, "jurors": jurors, "scheduled": False}

# ---------------------------
# Minimal IPFS storage fallback
# ---------------------------
def add_bytes(b: bytes):
    """
    Placeholder to add bytes to IPFS. Returns pseudo-CID if IPFS unavailable.
    """
    try:
        from .storage import NodeStorage
        node_storage = NodeStorage()
        return node_storage.add_bytes(b)
    except Exception:
        return f"cid-{hashlib.sha256(b).hexdigest()[:16]}"

class ProofOfHumanity:
    def __init__(self, ledger):
        self.ledger = ledger

    def apply_tier1(self, *args, **kwargs):
        return apply_tier1(*args, **kwargs)

    def apply_tier2(self, *args, **kwargs):
        return apply_tier2(*args, **kwargs)

    def apply_tier3(self, *args, **kwargs):
        return apply_tier3(*args, **kwargs)

    def juror_submit_vote(self, *args, **kwargs):
        return juror_submit_vote(*args, **kwargs)
# weall_runtime/poh_sync.py
from .poh import apply_tier2, apply_tier3, juror_submit_vote
from .sync import Node

class PoHNode(Node):
    """
    Extends Node to directly handle PoH application flows.
    """

    def submit_tier2_application(self, user_pub: str, video_cid: str, meta: dict):
        """
        Tier2 application flow:
        - deterministically choose jurors
        - persist application
        - return juror list for front-end notifications
        """
        return apply_tier2(user_pub, video_cid, meta, self)

    def submit_tier3_application(self, user_pub: str, requested_window: dict):
        """
        Tier3 live verification flow:
        - deterministically choose jurors
        - persist scheduling request
        """
        return apply_tier3(user_pub, requested_window, self)

    def process_juror_vote(self, app_id: str, juror_pub: str, vote: str, signature_b64: str):
        """
        Process a juror vote:
        - verify signature
        - store vote
        - finalize PoH if threshold reached
        """
        return juror_submit_vote(app_id, juror_pub, vote, signature_b64)
# weall_runtime/storage.py
"""
Storage abstraction for WeAll that supports:
- IPFS (if ipfshttpclient is available)
- Local fallback storage (useful for testing / CI / offline dev)

API:
- IPFSClient.connect()  # returns client
- client.add_str(content) -> cid
- client.get_str(cid) -> content
- client.pin(cid) -> None (no-op fallback)
"""

import os
import json
import hashlib
from typing import Optional

# Try to import ipfshttpclient; if missing, we'll use local store
try:
    import ipfshttpclient  # type: ignore
    _HAS_IPFS = True
except Exception:
    ipfshttpclient = None
    _HAS_IPFS = False

DEFAULT_LOCAL_DIR = os.path.join(os.getcwd(), ".weall_ipfs_store")


class IPFSClient:
    def __init__(self, local_dir: Optional[str] = None):
        self.local_dir = local_dir or DEFAULT_LOCAL_DIR
        os.makedirs(self.local_dir, exist_ok=True)
        self._client = None
        if _HAS_IPFS:
            try:
                self._client = ipfshttpclient.connect()
            except Exception:
                self._client = None

    def is_ipfs_available(self) -> bool:
        return self._client is not None

    # --- helpers for local fallback ---
    def _local_cid_for(self, content: str) -> str:
        # deterministic cid-like id using sha256 hex
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"local-{h}"

    def _local_path(self, cid: str) -> str:
        return os.path.join(self.local_dir, cid + ".json")

    # --- public API ---
    def add_str(self, content: str) -> str:
        """
        Add content to IPFS if available, otherwise to local store.
        Returns a cid (string).
        """
        if self._client:
            try:
                # ipfshttpclient has add_str in older versions; fallback to add_bytes
                try:
                    cid = self._client.add_str(content)
                    return str(cid)
                except Exception:
                    res = self._client.add_bytes(content.encode("utf-8"))
                    # add_bytes returns a multihash; return str
                    return str(res)
            except Exception:
                # fallthrough to local
                pass

        # local fallback
        cid = self._local_cid_for(content)
        path = self._local_path(cid)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"content": content}, f)
        return cid

    def get_str(self, cid: str) -> Optional[str]:
        """
        Retrieve content by cid. Returns None if not found.
        """
        if self._client:
            try:
                # try cat
                try:
                    raw = self._client.cat(cid)
                    if isinstance(raw, bytes):
                        return raw.decode("utf-8")
                    return str(raw)
                except Exception:
                    # try get and read file
                    res = self._client.get(cid)
                    # client.get writes to disk: try to read from returned path if present
                    if hasattr(res, "get") or isinstance(res, (list, dict)):
                        # not reliable across ipfshttpclient versions; fallback to local
                        pass
            except Exception:
                pass

        # local fallback
        path = self._local_path(cid)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return obj.get("content")
        return None

    def pin(self, cid: str) -> None:
        """
        Attempt to pin CID (no-op in local fallback).
        """
        if self._client:
            try:
                self._client.pin.add(cid)
            except Exception:
                pass
        return None
# weall_runtime/sync.py
import requests
import time
import json
import base64
from cryptography.fernet import Fernet
from weall_runtime.storage import IPFSClient

class Node:
    def __init__(self, ledger, peers=None):
        self.ledger = ledger
        self.peers = peers or []
        self.ipfs = IPFSClient()
        self.key = Fernet.generate_key()
        self.fernet = Fernet(self.key)

    def register_peer(self, url):
        if url not in self.peers:
            self.peers.append(url)

    def broadcast_snapshot(self):
        snapshot = self.ledger.snapshot()
        for peer in self.peers:
            try:
                requests.post(f"{peer}/sync/push", json=snapshot, timeout=2)
            except Exception as e:
                print(f"[sync] failed to push to {peer}: {e}")

    def fetch_from_peers(self):
        for peer in self.peers:
            try:
                resp = requests.get(f"{peer}/sync/snapshot", timeout=2)
                if resp.ok:
                    remote = resp.json()
                    # TODO: merge strategy (CRDT / last-write-wins)
                    print(f"[sync] received snapshot from {peer}")
            except Exception as e:
                print(f"[sync] failed to fetch from {peer}: {e}")

    def encrypt_and_store(self, content: str):
        token = self.fernet.encrypt(content.encode())
        return self.ipfs.add_bytes(token)

    def retrieve_and_decrypt(self, cid: str):
        data = self.ipfs.cat(cid)
        return self.fernet.decrypt(data).decode()

    def sync_loop(self, interval=10):
        while True:
            self.broadcast_snapshot()
            self.fetch_from_peers()
            time.sleep(interval)
# weall_runtime/utils.py
import hashlib, random
import json

def deterministic_shuffle(items, seed_bytes):
    """
    Deterministic shuffle: use SHA256(seed_bytes) as integer seed.
    items: list of items (e.g., pubkeys)
    seed_bytes: bytes
    """
    if isinstance(seed_bytes, str):
        seed_bytes = seed_bytes.encode("utf-8")
    seed_int = int(hashlib.sha256(seed_bytes).hexdigest(), 16)
    rng = random.Random(seed_int)
    items_copy = list(items)
    rng.shuffle(items_copy)
    return items_copy

def choose_jurors_for_application(node, count=10):
    """
    node.get_registered_jurors() should return list of dicts: {'pub':..., 'tier':(1|2|3), 'last_active':...}
    Prefer Tier 3 jurors. Deterministic seeded by latest block hash.
    """
    pool = node.get_registered_jurors()  # implement this on Node
    if not pool:
        return []
    tier3 = [p["pub"] for p in pool if p.get("tier") == 3]
    others = [p["pub"] for p in pool if p.get("tier") != 3]
    pool_order = tier3 + others
    seed = node.get_last_block_hashes(1)
    seed_bytes = seed[0].encode("utf-8") if seed else b"default-seed"
    shuffled = deterministic_shuffle(pool_order, seed_bytes)
    return shuffled[:count]

def simple_threshold_check(votes, threshold=7):
    """
    votes: iterable of 'approve'/'reject' strings
    returns True if approvals >= threshold
    """
    approvals = sum(1 for v in votes if v == "approve")
    return approvals >= threshold
"""
weall_runtime/wallet.py
Wallet + NFT management for Proof-of-Humanity, connected to ledger.
"""

from typing import Dict, List
from app_state import ledger  # ✅ connect to ledger

# In-memory storage for NFTs
NFT_REGISTRY: Dict[str, dict] = {}


def mint_nft(user_id: str, nft_id: str, metadata: str) -> dict:
    """
    Simulate minting an NFT and record it in the ledger.
    """
    nft = {
        "nft_id": nft_id,
        "owner": user_id,
        "metadata": metadata,
        "status": "minted",
    }
    NFT_REGISTRY[nft_id] = nft
    ledger.ledger.record_mint_event(user_id, nft_id)  # ✅ log event
    return nft


def transfer_nft(nft_id: str, new_owner: str) -> dict:
    """
    Transfer ownership of an NFT to another user and record in ledger.
    """
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    old_owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["owner"] = new_owner
    NFT_REGISTRY[nft_id]["status"] = "transferred"
    ledger.ledger.record_transfer_event(old_owner, new_owner, nft_id)  # ✅ log event
    return NFT_REGISTRY[nft_id]


def burn_nft(nft_id: str) -> dict:
    """
    Burn (remove) an NFT and record in ledger.
    """
    if nft_id not in NFT_REGISTRY:
        raise ValueError(f"NFT {nft_id} not found")

    owner = NFT_REGISTRY[nft_id]["owner"]
    NFT_REGISTRY[nft_id]["status"] = "burned"
    ledger.ledger.record_burn_event(owner, nft_id)  # ✅ log event
    return NFT_REGISTRY[nft_id]


def list_user_nfts(user_id: str) -> List[dict]:
    """
    Get all NFTs owned by a user.
    """
    return [n for n in NFT_REGISTRY.values() if n["owner"] == user_id]
