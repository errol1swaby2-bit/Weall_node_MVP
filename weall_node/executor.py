# executor.py — WeAll Node Core Orchestrator (v1.1)
# MPL-2.0

import os, json, time, uuid, random, pathlib
from collections import defaultdict
from typing import Optional, Dict, Any

try:
    import ipfshttpclient
except Exception:
    ipfshttpclient = None

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes


# -----------------------------------------------------
# YAML config loader
# -----------------------------------------------------
def _load_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml
        p = pathlib.Path(path)
        if p.exists():
            return yaml.safe_load(p.read_text()) or {}
    except Exception:
        pass
    return {}

CONFIG = _load_yaml(str(pathlib.Path(__file__).parent / "weall_config.yaml"))


# =========================================================
# Proof-of-Humanity (PoH) Gating Table
# =========================================================
POH_REQUIREMENTS = {
    "register": 0,
    "mint_poh_nft": 1,
    "produce_block": 3,
    "add_friend": 1,
    "send_message": 1,
    "view_content": 1,
    "report": 1,
    "post": 2,
    "comment": 2,
    "edit_post": 3,
    "delete_post": 3,
    "create_dispute": 1,
    "resolve_dispute": 3,
    "appeal_dispute": 3,
    "govern": 3,
    "submit_proposal": 3,
    "vote_proposal": 3,
    "execute_proposal": 3,
    "epoch_control": 3,
    "treasury_access": 3,
    "node_operator": 3,
    "storage_provider": 3,
}


def check_poh_access(state, user_id: str, action: str,
                     poh_requirements: dict = POH_REQUIREMENTS):
    """Return (bool, msg) based on PoH tier permissions."""
    user = state["users"].get(user_id)
    if not user:
        return False, "user_not_registered"
    required = poh_requirements.get(action, 0)
    level = int(user.get("poh_level", 0))
    if level < required:
        return False, f"requires_tier_{required}_poh"
    return True, "ok"


# -----------------------------------------------------
# Import runtime modules
# -----------------------------------------------------
from .weall_runtime.ledger import LedgerRuntime
from .weall_runtime.governance import GovernanceRuntime as GovernanceEngine
from .weall_runtime.storage import StorageRuntime
from .weall_runtime.participation import ParticipationRuntime
from .weall_runtime.poh import PoHRuntime
from .weall_runtime.wallet import WalletRuntime


# =========================================================
# Executor Orchestrator
# =========================================================
class WeAllExecutor:
    """
    Master orchestrator connecting all runtime modules
    and high-level user/social logic.
    """

    def __init__(self, poh_requirements: Optional[dict] = None):
        self.poh_requirements = poh_requirements or POH_REQUIREMENTS

        # --- Node identity
        self.node_id = uuid.uuid4().hex[:12]
        self.current_block_height = 0
        self.current_epoch = 0
        self.total_minted = 0.0

        # --- Core runtimes
        self.ledger = LedgerRuntime()
        self.storage = StorageRuntime()
        self.participation = ParticipationRuntime()
        self.poh = PoHRuntime()
        self.wallet = WalletRuntime(self.ledger)

        # --- Governance
        try:
            self.governance = GovernanceEngine()
            self.governance.attach_ledger(self.ledger)
            print("[WeAll] GovernanceEngine attached to executor.")
        except Exception as e:
            self.governance = None
            print(f"[WeAll] GovernanceEngine init failed: {e}")

        # --- State
        self.state = {
            "users": {},
            "friends": defaultdict(set),
            "posts": {},
            "comments": {},
            "messages": defaultdict(list),
            "treasury": defaultdict(float),
        }

        # --- Reward / Epoch configuration
        chain_cfg = CONFIG.get("chain", {})
        self.block_time_seconds = int(chain_cfg.get("block_time_seconds", 60))
        self.blocks_per_epoch = int(chain_cfg.get("blocks_per_epoch", 1440))
        self.initial_epoch_reward = float(chain_cfg.get("epoch_reward", 100.0))
        self.halving_interval_epochs = int(chain_cfg.get("halving_interval_epochs", 730))
        self.supply_cap = float(chain_cfg.get("supply_cap", 21_000_000))
        self.pool_split = CONFIG.get("reward_split", {
            "validators": 0.20, "jurors": 0.20, "creators": 0.30,
            "storage": 0.10, "treasury": 0.20,
        })

        # --- IPFS
        self.ipfs = None
        if ipfshttpclient:
            try:
                self.ipfs = ipfshttpclient.connect()
                print("[IPFS] Connected OK")
            except Exception as e:
                print(f"[IPFS] connection failed: {e}")

    # =========================================================
    # Core actions
    # =========================================================
    def register_user(self, uid: str, poh_level: int = 1):
        """Register a new user and create ledger/wallet account."""
        if uid in self.state["users"]:
            return {"ok": False, "error": "user_exists"}
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = priv.public_key()
        self.state["users"][uid] = {
            "poh_level": poh_level,
            "private_key": priv,
            "public_key": pub,
            "reputation": 0.0,
        }
        self.ledger.create_account(uid)
        self.wallet.create_account(uid)
        return {"ok": True, "user_id": uid}

    def create_post(self, uid: str, content: str, tags=None):
        """Create a content post if PoH level allows."""
        ok, msg = check_poh_access(self.state, uid, "post", self.poh_requirements)
        if not ok:
            return {"ok": False, "error": msg}
        ipfs_hash = self.storage.upload(content, self.ipfs)
        pid = len(self.state["posts"]) + 1
        self.state["posts"][pid] = {
            "user": uid, "content_hash": ipfs_hash,
            "tags": tags or [], "created": time.time(),
        }
        self.ledger.credit(uid, 10)
        return {"ok": True, "post_id": pid, "ipfs_hash": ipfs_hash}

    def mint_poh_nft(self, uid: str, tier: int):
        """Mint a PoH NFT and sync user tier."""
        res = self.poh.mint(uid, tier, self.ipfs)
        if res.get("ok") and uid in self.state["users"]:
            old = self.state["users"][uid].get("poh_level", 1)
            self.state["users"][uid]["poh_level"] = max(old, tier)
        return res

    # =========================================================
    # Wallet / Treasury
    # =========================================================
    def send_funds(self, sender: str, recipient: str, amount: float):
        """Transfer user funds through wallet runtime."""
        return self.wallet.transfer(sender, recipient, amount)

    def treasury_transfer(self, recipient: str, amount: float):
        """Transfer funds from community treasury."""
        if self.state["treasury"]["community_pool"] < amount:
            return {"ok": False, "error": "insufficient_treasury"}
        self.state["treasury"]["community_pool"] -= amount
        self.wallet.balances[recipient] = self.wallet.balances.get(recipient, 0) + amount
        return {"ok": True}

    # =========================================================
    # Participation / Governance
    # =========================================================
    def record_heartbeat(self, uid: str):
        """Record uptime for validators/storage nodes."""
        if hasattr(self.participation, "record_uptime"):
            self.participation.record_uptime(uid)
        return {"ok": True}

    def propose(self, creator: str, title: str, description: str, pallet: str, params=None):
        if not self.governance:
            return {"ok": False, "error": "governance_unavailable"}
        prop = self.governance.propose(creator, title, description, pallet, params)
        return {"ok": True, "proposal": prop}

    def vote(self, user_id: str, proposal_id: int, vote_option: str):
        if not self.governance:
            return {"ok": False, "error": "governance_unavailable"}
        return self.governance.vote(user_id, proposal_id, vote_option)

    def apply_governance_update(self, payload: dict):
        """Apply on-chain parameter changes from proposals."""
        for key, val in payload.items():
            if hasattr(self, key):
                setattr(self, key, val)
        return {"ok": True, "updated": list(payload.keys())}

    # =========================================================
    # Reward system
    # =========================================================
    def _halvings_elapsed(self, epoch=None):
        e = self.current_epoch if epoch is None else epoch
        return 0 if self.halving_interval_epochs <= 0 else e // self.halving_interval_epochs

    def _current_epoch_reward(self, epoch=None):
        h = self._halvings_elapsed(epoch)
        base = max(self.initial_epoch_reward / (2 ** h), 0.0)
        active_users = max(1, len(self.state["users"]))
        activity_factor = min(2.0, max(0.5, active_users / 1000.0))
        return base * activity_factor

    def on_new_block(self, producer: str):
        """Simulate block production and reward distribution."""
        h = self.current_block_height
        reward = self._current_epoch_reward(h // self.blocks_per_epoch) / self.blocks_per_epoch
        if reward <= 0:
            self.current_block_height += 1
            return {"ok": True, "minted": 0.0}

        minted = 0.0
        for pool, ratio in self.pool_split.items():
            amt = reward * float(ratio)
            if pool == "validators" and producer in self.state["users"]:
                self.ledger.credit(producer, amt)
            elif pool == "treasury":
                self.state["treasury"]["community_pool"] += amt
            minted += amt

        self.total_minted += minted
        self.current_block_height += 1
        self.current_epoch = self.current_block_height // self.blocks_per_epoch
        return {"ok": True, "height": self.current_block_height, "minted": minted}

    # =========================================================
    # Persistence
    # =========================================================
    def serialize_ledger(self):
        self.state["_ledger"] = getattr(self.ledger, "accounts", {})
        return {"ok": True}

    def restore_ledger(self):
        if "_ledger" in self.state:
            for uid, bal in self.state["_ledger"].items():
                self.ledger.accounts[uid] = bal
        return {"ok": True}

    def save_state(self, path="weall_state.json"):
        self.serialize_ledger()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, default=str)
        return {"ok": True}

    def load_state(self, path="weall_state.json"):
        if not os.path.exists(path):
            return {"ok": False, "error": "file_not_found"}
        with open(path, "r", encoding="utf-8") as f:
            self.state = json.load(f)
        self.restore_ledger()
        return {"ok": True}

    # =========================================================
    # Diagnostics
    # =========================================================
    def get_health(self):
        return {
            "ok": True,
            "node_id": self.node_id,
            "block_height": self.current_block_height,
            "epoch": self.current_epoch,
            "users": len(self.state["users"]),
            "governance": bool(self.governance),
            "ipfs": bool(self.ipfs),
            "treasury": self.state["treasury"].get("community_pool", 0.0),
        }
