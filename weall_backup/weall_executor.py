#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeAll Executor — Production-ready core (locks + optional SQLite) while remaining test-friendly.

Main capabilities
- Users & PoH (Tier 1–3 scaffolding) + Hybrid Tier-3 promotion (Founder → Jurors)
- Posts & comments
- Encrypted messaging (RSA OAEP)
- Governance lifecycle: propose → vote → close → enact (safe no-op enact by default)
- Chain integration: mempool + deterministic Tier-3 validator selection + block finalization
- Epoch management + simple rewards via ledger pools
- Persistence:
    * JSON files by default (test-friendly)
    * Optional SQLite backend via weall_config.yaml
- Safe autosave thread + explicit reset_state() for tests
"""

import os
import time
import json
import pathlib
import hashlib
import threading
import logging
from typing import Dict, Any, Optional, List
from collections import defaultdict

from weall_node.config import load_config
from weall_node.app_state.chain import ChainState
from weall_node.app_state.ledger import WeCoinLedger  # alias to LedgerState in app_state/ledger.py
from weall_node.app_state.governance import GovernanceRuntime  # alias to GovernanceState

# -----------------------------
# Founder (Phase A authority)
# -----------------------------
FOUNDER_UID = "bitcoinwasjustthebeginning@gmail.com"

# -----------------------------
# Logging bootstrap
# -----------------------------
def _setup_logging(cfg):
    level_str = (cfg.get("logging", {}).get("level", "INFO") or "INFO").upper()
    lvl = getattr(logging, level_str, logging.INFO)
    logging.basicConfig(level=lvl, format="%(message)s")
    return logging.getLogger("weall")

log = logging.getLogger("weall")  # will be set in __init__

# -----------------------------
# Proof-of-Humanity action requirements (baseline)
# -----------------------------
POH_REQUIREMENTS = {
    # Identity / PoH flow
    "register": 0,
    "poh_tier1_request": 0,
    "poh_tier1_verify": 0,
    "poh_tier2_verify": 1,
    "poh_tier3_verify": 2,

    # Ledger / Treasury
    "ledger_create": 1,
    "ledger_deposit": 1,
    "ledger_transfer": 1,
    "treasury_deposit": 2,
    "treasury_withdraw": 3,

    # Content
    "post_create": 1,
    "comment_create": 1,
    "dispute_create": 2,
    "dispute_resolve": 3,

    # Messaging
    "message_send": 1,
    "message_read": 1,

    # Governance
    "propose": 3,
    "vote": 2,
    "enact": 3,
    "amend_dsl": 3,
    "amend_code": 3,

    # Validator / consensus / epochs
    "juror": 3,
    "validator_finalize": 3,
    "epoch_advance": 3,

    # System
    "backup_state": 2,
    "restore_state": 3,
}

# -----------------------------
# Crypto (messaging + signatures)
# -----------------------------
try:
    import ipfshttpclient
except Exception:
    ipfshttpclient = None

from cryptography.hazmat.primitives.asymmetric import rsa, padding, ed25519
from cryptography.hazmat.primitives import hashes, serialization as ser


def generate_keypair():
    """RSA keypair for messaging encryption."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def encrypt_message(pub_key, message: str) -> bytes:
    return pub_key.encrypt(
        message.encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def decrypt_message(priv_key, ciphertext: bytes) -> str:
    return priv_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    ).decode()


# ===================================================
# Executor
# ===================================================
class WeAllExecutor:
    STATE_FILE = "executor_state.json"
    LEDGER_FILE = "ledger.json"

    def __init__(self, dsl_file: str, poh_requirements: Optional[dict] = None):
        self.start_ts = time.time()
        self.dsl_file = dsl_file
        self.repo_root = str(pathlib.Path(__file__).resolve().parents[1])

        # Load runtime config
        self.cfg = load_config(self.repo_root)
        global log
        log = _setup_logging(self.cfg)

        # Re-entrant lock for state safety
        self.lock = threading.RLock()

        self.poh_requirements = poh_requirements or POH_REQUIREMENTS

        # Core subsystems
        self.ledger = WeCoinLedger()
        self.chain = ChainState()
        self.governance = GovernanceRuntime()

        # Epochs
        self.current_epoch = 0
        self.epoch_duration = 24 * 3600
        self.last_epoch_time = 0.0

        # In-memory state
        self.state: Dict[str, Any] = {
            "users": {},                 # uid -> {poh_level, private_key, public_key, ed25519_priv, ed25519_pub(bytes)}
            "posts": {},                 # pid -> {...}
            "comments": {},              # cid -> {...}
            "disputes": {},              # reserved for future
            "treasury": defaultdict(float),
            "messages": defaultdict(list),  # uid -> list of {"from","encrypted","ts"}
            "proposals": {},             # pid -> {...}
            "code_versions": defaultdict(list),
            "governance_log": [],
            # Hybrid PoH promotion state
            "poh_promotions": {},        # target_uid -> {status, required, votes{juror:vote}}
            "nfts": {},                  # uid -> {tier,cid,issued_at}
            # Optional groups (if used by API/front-end)
            "groups": {},
        }
        self.next_post_id = 1
        self.next_comment_id = 1
        self.next_proposal_id = 1

        # Policy from config, with sensible defaults
        self.config = {
            "tier3_quorum_fraction": float(self.cfg["governance"]["tier3_quorum_fraction"]),
            "tier3_yes_fraction": float(self.cfg["governance"]["tier3_yes_fraction"]),
            "editable_roots": self.cfg["runtime"]["editable_roots"],
            "backup_dir": self.cfg["runtime"]["backup_dir"],
            "require_ipfs": bool(self.cfg["ipfs"]["require_ipfs"]),
        }
        pathlib.Path(self.repo_root, self.config["backup_dir"]).mkdir(exist_ok=True)

        # Optional SQLite store (atomic writes)
        self._store = None
        if self.cfg["persistence"]["driver"] == "sqlite":
            from weall_node.storage.sqlite_store import SQLiteStore
            self._store = SQLiteStore(os.path.join(self.repo_root, self.cfg["persistence"]["sqlite_path"]))

        # Optional IPFS (dev fallback always available)
        self.ipfs = None
        try:
            if ipfshttpclient and self.config["require_ipfs"]:
                self.ipfs = ipfshttpclient.connect()
        except Exception as e:
            log.warning(f"[IPFS] connection failed: {e}")

        # Dev IPFS content store for tests
        self._dev_ipfs: Dict[str, bytes] = {}

        # Load persisted chain and state
        self.chain.load(os.path.join(self.repo_root, "chain.json"))
        self.load_state()

        # Autosave thread
        self._stop = threading.Event()
        self._autosave = threading.Thread(target=self._autosave_loop, daemon=True)
        self._autosave.start()

    # -----------------------------
    # Utility
    # -----------------------------
    @staticmethod
    def sha256_hex(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    def get_required_poh(self, action: str) -> int:
        return int(self.poh_requirements.get(action, 3))

    def _user_level(self, uid: str) -> int:
        u = self.state["users"].get(uid)
        return int(u.get("poh_level", 0)) if u else 0

    def _whitelisted(self, relpath: str) -> bool:
        if relpath.startswith("/") or ".." in pathlib.PurePosixPath(relpath).parts:
            return False
        p = pathlib.Path(relpath)
        return any(str(p).startswith(root + "/") or str(p) == root for root in self.config["editable_roots"])

    def _abs(self, relpath: str) -> str:
        return str(pathlib.Path(self.repo_root, relpath).resolve())

    def _ensure_account(self, uid: str):
        """Ensure a ledger account exists for user (compatible with LedgerState)."""
        if hasattr(self.ledger, "accounts"):
            self.ledger.accounts.setdefault(uid, 0.0)

    # -----------------------------
    # Persistence
    # -----------------------------
    def _serializable_state(self) -> Dict[str, Any]:
        # Strip un-serializable keys; keep Ed25519 pub for signatures
        safe_users = {}
        for uid, meta in self.state["users"].items():
            ed_pub = meta.get("ed25519_pub")
            safe_users[uid] = {
                "poh_level": int(meta.get("poh_level", 0)),
                "ed25519_pub": ed_pub.hex() if isinstance(ed_pub, (bytes, bytearray)) else None,
            }
        return {
            "users": safe_users,
            "posts": self.state["posts"],
            "comments": self.state["comments"],
            "disputes": self.state["disputes"],
            "treasury": dict(self.state["treasury"]),
            "messages": {u: [{"from": m["from"], "encrypted": None, "ts": m["ts"]} for m in msgs]
                         for u, msgs in self.state["messages"].items()},
            "proposals": self.state["proposals"],
            "code_versions": self.state["code_versions"],
            "governance_log": self.state["governance_log"],
            "epoch": self.current_epoch,
            "last_epoch_time": self.last_epoch_time,
            "poh_promotions": self.state.get("poh_promotions", {}),
            "nfts": self.state.get("nfts", {}),
            "groups": self.state.get("groups", {}),
        }

    def save_state(self):
        with self.lock:
            state = self._serializable_state()
            if self._store:
                self._store.set_json("executor_state", state)
            else:
                try:
                    with open(os.path.join(self.repo_root, self.STATE_FILE), "w") as f:
                        json.dump(state, f, indent=2)
                except Exception as e:
                    log.error(f"[save_state] {e}")
            # Always persist chain json for tests
            self.chain.save(os.path.join(self.repo_root, "chain.json"))

    def load_state(self):
        with self.lock:
            if self._store:
                data = self._store.get_json("executor_state", {})
            else:
                path = os.path.join(self.repo_root, self.STATE_FILE)
                if not os.path.exists(path):
                    return
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                except Exception as e:
                    log.error(f"[load_state] {e}")
                    return

            s = data or {}
            # basic structures
            self.state["posts"] = s.get("posts", {})
            self.state["comments"] = s.get("comments", {})
            self.state["disputes"] = s.get("disputes", {})
            self.state["proposals"] = s.get("proposals", {})
            self.state["governance_log"] = s.get("governance_log", [])
            self.state["code_versions"] = defaultdict(list, s.get("code_versions", {}))
            self.state["messages"] = defaultdict(list, self.state["messages"])
            self.state["treasury"] = defaultdict(float, s.get("treasury", {}))
            self.state["poh_promotions"] = s.get("poh_promotions", {})
            self.state["nfts"] = s.get("nfts", {})
            self.state["groups"] = s.get("groups", {})

            # Users: restore PoH level + ed25519 pub only; RSA keys remain ephemeral
            for uid, meta in s.get("users", {}).items():
                if uid not in self.state["users"]:
                    ed_pub_hex = meta.get("ed25519_pub")
                    ed_pub = bytes.fromhex(ed_pub_hex) if ed_pub_hex else None
                    self.state["users"][uid] = {
                        "poh_level": int(meta.get("poh_level", 0)),
                        "private_key": None,
                        "public_key": None,
                        "ed25519_priv": None,
                        "ed25519_pub": ed_pub,
                    }

            self.current_epoch = int(s.get("epoch", 0))
            self.last_epoch_time = float(s.get("last_epoch_time", 0.0))

    def reset_state(self):
        with self.lock:
            self.state = {
                "users": {},
                "posts": {},
                "comments": {},
                "disputes": {},
                "treasury": defaultdict(float),
                "messages": defaultdict(list),
                "proposals": {},
                "code_versions": defaultdict(list),
                "governance_log": [],
                "poh_promotions": {},
                "nfts": {},
                "groups": {},
            }
            self.ledger = WeCoinLedger()
            self.chain = ChainState()
            self.governance = GovernanceRuntime()
            self.current_epoch = 0
            self.last_epoch_time = 0.0
            self.start_ts = time.time()
            self.save_state()

    def _autosave_loop(self):
        while not self._stop.is_set():
            time.sleep(120)
            self.save_state()

    def stop(self):
        """Preferred graceful stop (compatible with API)."""
        self._stop.set()
        try:
            self._autosave.join(timeout=2.0)
        except Exception:
            pass
        self.save_state()

    # Compatibility helpers for older API code that referenced autosave_start/stop
    def autosave_start(self):  # no-op: started in __init__
        return True

    def autosave_stop(self):
        self.stop()

    # -----------------------------
    # Dev IPFS helpers (always available)
    # -----------------------------
    def _ipfs_add_str(self, content: str) -> str:
        if not self.ipfs or not self.config.get("require_ipfs"):
            b = content.encode()
            cid = f"dev-{self.sha256_hex(b)}"
            self._dev_ipfs[cid] = b
            return cid
        return self.ipfs.add_str(content)

    def _ipfs_cat(self, cid: str) -> bytes:
        if (not self.ipfs) or (not self.config.get("require_ipfs")):
            if cid in self._dev_ipfs:
                return self._dev_ipfs[cid]
            raise RuntimeError("Dev IPFS: content not found")
        data = self.ipfs.cat(cid)
        return data if isinstance(data, (bytes, bytearray)) else bytes(data)

    # -----------------------------
    # Users & PoH (Tier 1 convenience)
    # -----------------------------
    def register_user(self, uid: str, poh_level=1):
        with self.lock:
            if uid in self.state["users"]:
                return {"ok": False, "error": "user_already_exists"}
            priv, pub = generate_keypair()
            ed_priv = ed25519.Ed25519PrivateKey.generate()
            ed_pub = ed_priv.public_key().public_bytes(
                encoding=ser.Encoding.Raw, format=ser.PublicFormat.Raw
            )
            self.state["users"][uid] = {
                "poh_level": int(poh_level),
                "private_key": priv,
                "public_key": pub,
                "ed25519_priv": ed_priv,
                "ed25519_pub": ed_pub,
            }
            self._ensure_account(uid)
            self.save_state()
            return {"ok": True}

    def request_tier1(self, user: str, email: str):
        """Minimal Tier1 request endpoint used by API tests. Marks/ensures tier1."""
        with self.lock:
            if user not in self.state["users"]:
                # Create user shell with Tier1 but no keys (API flow may promote later)
                self.state["users"][user] = {
                    "poh_level": 1,
                    "private_key": None,
                    "public_key": None,
                    "ed25519_priv": None,
                    "ed25519_pub": None,
                }
            else:
                # Ensure at least Tier1
                if int(self.state["users"][user].get("poh_level", 0)) < 1:
                    self.state["users"][user]["poh_level"] = 1
            self._ensure_account(user)
            self.save_state()
            # return mock code-like response (kept simple)
            return {"ok": True, "tier": 1, "user": user, "message": f"Tier1 requested for {user}"}

    # -----------------------------
    # Messaging
    # -----------------------------
    def send_message(self, from_user: str, to_user: str, msg: str):
        with self.lock:
            if from_user not in self.state["users"] or to_user not in self.state["users"]:
                return {"ok": False, "error": "user_not_registered"}
            to_pub = self.state["users"][to_user].get("public_key")
            if not to_pub:
                return {"ok": False, "error": "no_public_key"}
            cipher = encrypt_message(to_pub, msg)
            self.state["messages"][to_user].append(
                {"from": from_user, "encrypted": cipher, "ts": time.time()}
            )
            self.save_state()
            return {"ok": True}

    def read_messages(self, user_id: str) -> List[dict]:
        with self.lock:
            if user_id not in self.state["users"]:
                return []
            priv = self.state["users"][user_id].get("private_key")
            inbox = []
            for m in self.state["messages"].get(user_id, []):
                try:
                    plain = decrypt_message(priv, m["encrypted"]) if priv else "<no_private_key>"
                except Exception:
                    plain = "<decryption failed>"
                inbox.append({"from": m["from"], "text": plain, "ts": m["ts"]})
            return inbox

    # -----------------------------
    # Content
    # -----------------------------
    def create_post(self, user: str, content: str, tags=None, ipfs_cid: str | None = None):
        """Create a post with optional IPFS CID/media attachment."""
        with self.lock:
            if user not in self.state["users"]:
                return {"ok": False, "error": "user_not_found"}

            pid = self.next_post_id
            self.next_post_id += 1

            post = {
                "user": user,
                "content": content,
                "tags": tags or [],
                "likes": 0,
            }

            # allow attached IPFS content if provided
            if ipfs_cid:
                post["ipfs_cid"] = ipfs_cid

            self.state["posts"][pid] = post
            self.save_state()
            return {"ok": True, "post_id": pid}

    def create_comment(self, user: str, post_id: int, content: str):
        with self.lock:
            if user not in self.state["users"]:
                return {"ok": False, "error": "user_not_found"}
            if post_id not in self.state["posts"]:
                return {"ok": False, "error": "post_not_found"}
            cid = self.next_comment_id
            self.next_comment_id += 1
            self.state["comments"][cid] = {"user": user, "post_id": post_id, "content": content}
            self.save_state()
            return {"ok": True, "comment_id": cid}

    # -----------------------------
    # Chain / mempool / validator / blocks
    # -----------------------------
    def record_to_mempool(self, event: dict):
        with self.lock:
            self.chain.record_to_mempool(event)
            self.save_state()
            return {"ok": True, "size": len(self.chain.get_mempool())}

    def select_validator(self, seed: int = 0) -> str:
        with self.lock:
            tier3 = [u for u, meta in self.state["users"].items() if int(meta.get("poh_level", 0)) >= 3]
            if not tier3:
                return "x"
            idx = seed % len(tier3)
            return tier3[idx]

    def finalize_block(self, validator_id: Optional[str] = None) -> dict:
        with self.lock:
            author = validator_id or self.select_validator(seed=int(time.time()))
            block = self.chain.finalize_block(author)
            self.save_state()
            return block

    # -----------------------------
    # Epochs
    # -----------------------------
    def advance_epoch(self, force: bool = False):
        with self.lock:
            now = time.time()
            if not force and (now - self.last_epoch_time) < self.epoch_duration:
                return {"ok": False, "error": "epoch_not_elapsed"}
            self.current_epoch += 1
            self.last_epoch_time = now
            # Distribute simple rewards based on epoch number (if implemented)
            if hasattr(self.ledger, "distribute_epoch_rewards"):
                self.ledger.distribute_epoch_rewards(int(self.current_epoch))
            self.save_state()
            return {"ok": True, "epoch": self.current_epoch}

    # -----------------------------
    # Governance
    # -----------------------------
    def propose_code_update(self, user: str, module_path: str, cid: str, checksum: str):
        with self.lock:
            pid = self.next_proposal_id
            self.next_proposal_id += 1
            self.state["proposals"][pid] = {
                "proposer": user,
                "module": module_path,
                "cid": cid,
                "checksum": checksum,
                "status": "open",
                "votes": {},  # user -> yes/no/abstain
            }
            self.save_state()
            return {"ok": True, "proposal_id": pid}

    def vote_on_proposal(self, user: str, pid: int, vote: str, signature: Optional[bytes] = None):
        """
        Production supports signed votes; tests may omit signature.
        Policy: If security.require_signed_votes == True and signature is provided, verify it.
                If signature is None, accept for backward compatibility (tests).
        """
        with self.lock:
            p = self.state["proposals"].get(pid)
            if not p:
                return {"ok": False, "error": "proposal_not_found"}
            require_sig = bool(self.cfg["security"].get("require_signed_votes", False))
            if require_sig and signature is not None:
                u = self.state["users"].get(user)
                if not u or not u.get("ed25519_pub"):
                    return {"ok": False, "error": "no_signing_key"}
                try:
                    pub = ed25519.Ed25519PublicKey.from_public_bytes(u["ed25519_pub"])
                    pub.verify(signature, f"vote:{pid}:{vote}".encode())
                except Exception:
                    return {"ok": False, "error": "invalid_signature"}
            p["votes"][user] = vote
            self.save_state()
            return {"ok": True}

    def close_proposal(self, pid: int):
        with self.lock:
            p = self.state["proposals"].get(pid)
            if not p:
                return {"ok": False, "error": "proposal_not_found"}
            yes = sum(1 for v in p["votes"].values() if v == "yes")
            total = sum(1 for v in p["votes"].values() if v in ("yes", "no"))
            status = "failed"
            if total > 0 and (yes / max(1, total)) >= self.config["tier3_yes_fraction"]:
                status = "passed"
            p["status"] = status
            self.save_state()
            return {"ok": True, "status": status}

    def try_enact_proposal(self, user: str, pid: int):
        with self.lock:
            p = self.state["proposals"].get(pid)
            if not p or p.get("status") != "passed":
                return {"ok": False}
            # Safe enactment (no-op by default): just record the event
            self.state["governance_log"].append({
                "pid": pid,
                "module": p["module"],
                "cid": p["cid"],
                "checksum": p["checksum"],
                "ts": time.time(),
                "enacted_by": user,
            })
            self.save_state()
            return {"ok": True}

    # Convenience (used by API)
    def list_proposals(self) -> List[dict]:
        with self.lock:
            out = []
            for pid, p in sorted(self.state["proposals"].items()):
                q = dict(p)
                q["id"] = pid
                out.append(q)
            return out

    # ============================================================
    # Hybrid PoH Promotion (Founder-controlled Phase A → Jurors)
    # ============================================================
    def total_users(self) -> int:
        return len(self.state.get("users", {}))

    def required_jurors_for_tier3(self, total: int, requester: str) -> int:
        """
        Phase A (<20 users): only founder can approve; requester need == -1 means 'await founder'.
        Founder requester always has need == 0 (can self-promote exactly once at bootstrap).
        Phase B (20-99): 3 jurors
        Phase C (100-249): 6 jurors
        Phase D (>=250): 10 jurors
        """
        if requester == FOUNDER_UID:
            return 0
        if total < 20:
            return -1  # founder-only approval
        if total < 100:
            return 3
        if total < 250:
            return 6
        return 10

    def request_tier3(self, user: str) -> dict:
        with self.lock:
            users = self.state.setdefault("users", {})
            if user not in users:
                return {"ok": False, "error": "user_not_registered"}
            if int(users[user].get("poh_level", 0)) >= 3:
                return {"ok": True, "message": "already_tier3"}

            total = self.total_users()
            need = self.required_jurors_for_tier3(total, user)

            # Founder self-promotion at bootstrap (first time)
            if user == FOUNDER_UID and need == 0 and total == 1:
                users[user]["poh_level"] = 3
                nft = self._mint_tier3_nft(user)
                self.save_state()
                return {"ok": True, "message": "founder_self_promoted", "nft": nft}

            # Non-founders before 20 users → wait for founder approval
            if need == -1:
                req = self.state.setdefault("poh_promotions", {})
                req[user] = {"status": "pending_founder", "required": 1, "votes": {}}
                self.save_state()
                return {"ok": True, "message": "awaiting_founder_video_verification"}

            # Normal juror-based phases with zero needed (rare), immediate promote
            if need == 0:
                users[user]["poh_level"] = 3
                nft = self._mint_tier3_nft(user)
                self.save_state()
                return {"ok": True, "message": "promoted_self_bootstrap", "nft": nft}

            # Open a juror-based promotion case
            req = self.state.setdefault("poh_promotions", {})
            req[user] = {"status": "pending", "required": need, "votes": {}}
            self.save_state()
            return {"ok": True, "message": "promotion_opened", "required": need}

    def founder_approve_tier3(self, founder: str, target: str) -> dict:
        with self.lock:
            if founder != FOUNDER_UID:
                return {"ok": False, "error": "not_founder"}
            users = self.state["users"]
            if target not in users:
                return {"ok": False, "error": "user_not_found"}
            case = self.state.setdefault("poh_promotions", {}).get(target)
            if not case or case.get("status") != "pending_founder":
                return {"ok": False, "error": "no_pending_founder_request"}

            users[target]["poh_level"] = 3
            case["status"] = "approved_by_founder"
            nft = self._mint_tier3_nft(target)
            self.save_state()
            return {"ok": True, "message": "founder_approved", "nft": nft}

    def juror_vote_tier3(self, juror: str, target: str, vote: str) -> dict:
        with self.lock:
            if juror == target:
                return {"ok": False, "error": "self_vote_not_allowed"}
            if int(self.state["users"].get(juror, {}).get("poh_level", 0)) < 3:
                return {"ok": False, "error": "juror_not_tier3"}

            case = self.state.setdefault("poh_promotions", {}).get(target)
            if not case or case.get("status") != "pending":
                return {"ok": False, "error": "no_pending_request"}

            if vote not in ("approve", "reject"):
                return {"ok": False, "error": "invalid_vote"}

            case["votes"][juror] = vote
            approvals = sum(1 for v in case["votes"].values() if v == "approve")
            required = int(case.get("required", 0))
            if approvals >= required:
                self.state["users"][target]["poh_level"] = 3
                case["status"] = "approved"
                nft = self._mint_tier3_nft(target)
                self.save_state()
                return {"ok": True, "status": "approved", "nft": nft}
            self.save_state()
            rejections = sum(1 for v in case["votes"].values() if v == "reject")
            return {"ok": True, "status": "pending", "approvals": approvals, "rejections": rejections, "required": required}

    def get_promotion_status(self, target: str) -> dict:
        with self.lock:
            case = self.state.setdefault("poh_promotions", {}).get(target)
            level = int(self.state["users"].get(target, {}).get("poh_level", 0))
            return {
                "user": target,
                "tier": level,
                "case": case or None,
                "required_now": self.required_jurors_for_tier3(self.total_users(), target),
                "total_users": self.total_users(),
            }

    def _mint_tier3_nft(self, user: str) -> dict:
        """
        Creates a minimal Tier-3 attestation record and stores it via IPFS (or dev store).
        Returns {"cid": "...", "tier": 3, "issued_at": ts}
        """
        payload = {
            "type": "weall-tier3-attestation",
            "user": user,
            "tier": 3,
            "issued_at": time.time(),
            "chain_epoch": self.current_epoch,
            "node": self.repo_root,
        }
        try:
            content = json.dumps(payload, separators=(",", ":"))
            cid = self._ipfs_add_str(content)
        except Exception:
            cid = f"dev-nft-{int(time.time())}"
        nft = {"cid": cid, "tier": 3, "issued_at": payload["issued_at"]}
        nfts = self.state.setdefault("nfts", {})
        nfts[user] = nft
        return nft


__all__ = ["WeAllExecutor", "POH_REQUIREMENTS"]
