import time
from collections import defaultdict
from typing import List, Dict, Optional

# Runtime modules
from .weall_runtime import (
    crypto_utils,
    SimpleFernet,
    LedgerRuntime as Ledger,
    GovernanceRuntime as Governance,
    PoHRuntime as PoH,
    GLOBAL_PARAMS,
    BlockTimeScheduler,
)

# Chain state
from weall_node.app_state.chain import chain_instance


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
    "mint_nft": 2,
}

def _now() -> float:
    return time.time()


class WeAllExecutor:
    def __init__(self, poh_requirements: Optional[Dict[str, int]] = None,
                 auto_scheduler: bool = False,
                 bootstrap_mode: bool = True,
                 min_validators: int = 3):
        self.poh_requirements = poh_requirements or POH_REQUIREMENTS
        self.bootstrap_mode = bootstrap_mode
        self.min_validators = min_validators

        # Runtime subsystems
        self.ledger = Ledger()
        self.gov = Governance()
        self.poh = PoH()

        self.gov.attach_ledger(self.ledger)
        if hasattr(self.poh, "attach_executor"):
            self.poh.attach_executor(self)

        # ✅ Fix: Pass executor object, not advance_epoch fn
        self.scheduler = None
        if auto_scheduler:
            self.scheduler = BlockTimeScheduler(
                self,  # <-- pass whole executor
                interval_seconds=GLOBAL_PARAMS.get("block_time", 600)
            )
            self.scheduler.start()

        # Local state
        self.current_epoch = 0
        self.state = {
            "users": {},
            "posts": {},
            "comments": {},
            "profiles": {},
            "proposals": {},
            "disputes": {},
            "treasury": defaultdict(float),
            "messages": defaultdict(list),
            "groups": {},
            "replication_assignments": defaultdict(list),
            "operator_uptime": defaultdict(lambda: {"ok": 0, "fail": 0, "last": 0}),
        }
        self.next_post_id = 1
        self.next_comment_id = 1
        self.next_proposal_id = 1
        self.next_dispute_id = 1

        # Ensure pools exist
        self._ensure_pool("validators")
        self._ensure_pool("operators")

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------
    def _ensure_pool(self, pool_name: str):
        pools = getattr(self.ledger.wecoin, "pools", None)
        if pools is None:
            self.ledger.wecoin.pools = {}
            pools = self.ledger.wecoin.pools
        if pool_name not in pools:
            self.ledger.wecoin.pools[pool_name] = {"members": []}

    def _ledger_pool_add(self, pool: str, user_id: str):
        self._ensure_pool(pool)
        self.ledger.wecoin.add_to_pool(pool, user_id)

    def _ledger_pool_remove(self, pool: str, user_id: str):
        self._ensure_pool(pool)
        self.ledger.wecoin.remove_from_pool(pool, user_id)

    # ---------------------------------------------------------------
    # Epoch
    # ---------------------------------------------------------------
    def advance_epoch(self):
        self.current_epoch += 1
        winners = self.ledger.advance_epoch(bootstrap_mode=self.bootstrap_mode)
        elected = self.elected_validator(self.current_epoch)
        return {"ok": True, "epoch": self.current_epoch, "winners": winners, "elected": elected}

    # ---------------------------------------------------------------
    # PoH
    # ---------------------------------------------------------------
    def check_poh(self, user_id, action) -> bool:
        required = self.poh_requirements.get(action, 1)
        user = self.state["users"].get(user_id)
        return bool(user and user.get("poh_level", 0) >= required)

    # ---------------------------------------------------------------
    # Reputation
    # ---------------------------------------------------------------
    def grant_reputation(self, user_id, amount: int):
        if user_id in self.state["users"]:
            self.state["users"][user_id]["reputation"] += int(amount)

    def slash_reputation(self, user_id, amount: int):
        if user_id in self.state["users"]:
            self.state["users"][user_id]["reputation"] = max(
                0, self.state["users"][user_id]["reputation"] - int(amount)
            )

    # ---------------------------------------------------------------
    # Users
    # ---------------------------------------------------------------
    def register_user(self, user_id: str, poh_level: int = 1, profile: Optional[Dict] = None):
        if user_id in self.state["users"]:
            return {"ok": False, "error": "user_already_exists"}
        priv, pub = crypto_utils.generate_keypair()
        self.state["users"][user_id] = {
            "poh_level": poh_level,
            "reputation": 0,
            "friends": [],
            "groups": [],
            "private_key": priv,
            "public_key": pub,
            "is_validator": False,
            "is_operator": False,
        }
        self.state["profiles"][user_id] = profile or {"bio": "", "avatar_cid": None, "created": _now()}
        self.ledger.wecoin.create_account(user_id)
        return {"ok": True}

    # ---------------------------------------------------------------
    # Validators
    # ---------------------------------------------------------------
    def opt_in_validator(self, user_id: str):
        u = self.state["users"].get(user_id)
        if not u or u.get("poh_level", 0) < 3:
            return {"ok": False, "error": "not_tier3"}
        if u.get("is_validator"):
            return {"ok": True, "note": "already_opted_in"}
        u["is_validator"] = True
        self._ledger_pool_add("validators", user_id)
        return {"ok": True}

    def opt_out_validator(self, user_id: str):
        u = self.state["users"].get(user_id)
        if not u or not u.get("is_validator"):
            return {"ok": False, "error": "not_in_validator_pool"}
        u["is_validator"] = False
        self._ledger_pool_remove("validators", user_id)
        return {"ok": True}

    def get_validators(self) -> List[str]:
        pool = self.ledger.wecoin.pools.get("validators", {}).get("members", [])
        return sorted([uid for uid in pool if self.state["users"].get(uid, {}).get("poh_level", 0) >= 3])

    def elected_validator(self, epoch: Optional[int] = None) -> Optional[str]:
        vals = self.get_validators()
        if not vals:
            return None
        if self.bootstrap_mode and len(vals) < self.min_validators:
            return sorted(vals)[0]
        if epoch is None:
            epoch = self.current_epoch
        return vals[epoch % len(vals)]

    def run_validator(self, user_id: str):
        if not self.is_validator(user_id):
            return {"ok": False, "error": "not_tier3_validator"}

        elected = self.elected_validator()

        if self.bootstrap_mode and len(self.get_validators()) < self.min_validators:
            elected = user_id

        if user_id != elected:
            self.slash_reputation(user_id, 1)
            return {"ok": False, "error": f"not_elected_this_epoch (elected={elected})"}

        priv = self.state["users"][user_id]["private_key"]
        pub = self.state["users"][user_id]["public_key"]
        block = chain_instance.produce_block(user_id, priv, pub, crypto_utils)

        if not self.bootstrap_mode:
            proposer_coin = int(GLOBAL_PARAMS.get("block_reward", 20))
            proposer_rep  = int(GLOBAL_PARAMS.get("block_rep_reward", 2))
            self.ledger.wecoin.deposit(user_id, proposer_coin)
            self.grant_reputation(user_id, proposer_rep)
        else:
            proposer_coin = 0
            proposer_rep = 1
            self.grant_reputation(user_id, proposer_rep)

        if self.bootstrap_mode and len(self.get_validators()) >= self.min_validators:
            self.bootstrap_mode = False

        return {
            "ok": True,
            "epoch": self.current_epoch,
            "elected": elected,
            "block_hash": block["hash"],
            "txs": len(block["txs"]),
            "proposer_coin": proposer_coin,
            "proposer_rep": proposer_rep,
            "bootstrap_mode": self.bootstrap_mode,
        }

    def is_validator(self, user_id: str) -> bool:
        return user_id in self.get_validators()

    # ---------------------------------------------------------------
    # Operators
    # ---------------------------------------------------------------
    def opt_in_operator(self, user_id: str):
        u = self.state["users"].get(user_id)
        if not u or u.get("poh_level", 0) < 3:
            return {"ok": False, "error": "not_tier3"}
        if u.get("is_operator"):
            return {"ok": True, "note": "already_opted_in"}
        u["is_operator"] = True
        self._ledger_pool_add("operators", user_id)
        return {"ok": True}

    def opt_out_operator(self, user_id: str):
        u = self.state["users"].get(user_id)
        if not u or not u.get("is_operator"):
            return {"ok": False, "error": "not_in_operator_pool"}
        u["is_operator"] = False
        self._ledger_pool_remove("operators", user_id)
        return {"ok": True}

    def _current_operators(self) -> List[str]:
        pool = self.ledger.wecoin.pools.get("operators", {}).get("members", [])
        return sorted([uid for uid in pool if self.state["users"].get(uid, {}).get("is_operator")])
