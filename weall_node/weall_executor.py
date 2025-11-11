# weall_node/weall_executor.py
"""
WeAll Executor — unified runtime with quorum finalization + dev mining (PBFT-lite)

This merges the “toy finality” flow and the production-leaning quorum flow:
- DEV MINE (legacy): executor.mine_block([optional_payload]) → propose→self-vote→finalize
- QUORUM: propose_block(proposer_id) + vote_block(validator_id, proposal_id) → finalize on quorum
- Legacy/alias: attest_block(validator_id, proposal_id) == vote_block(...)

Back-compat: keeps prior method names & attribute access used by API modules (PoH, ledger, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger("weall.executor")


# ------------------------------------------------------------
# Helpers / persistence
# ------------------------------------------------------------
def _repo_root() -> str:
    # this file lives in weall_node/ ; repo root = parent
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _state_path() -> str:
    return os.path.join(_repo_root(), "weall_state.json")


def _now() -> int:
    return int(time.time())


# ------------------------------------------------------------
# Minimal P2P manager (keeps API working)
# ------------------------------------------------------------
class P2PManager:
    def __init__(self) -> None:
        self._peers: Set[str] = set()

    def add_peer(self, peer_id: str) -> None:
        if peer_id:
            self._peers.add(str(peer_id))

    def get_peer_list(self) -> List[str]:
        return sorted(self._peers)


# ------------------------------------------------------------
# Governance placeholder
# ------------------------------------------------------------
@dataclass
class GovernanceState:
    proposals: List[Dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------
# Consensus state (PBFT-lite / PoA-lite)
# ------------------------------------------------------------
class ConsensusState:
    def __init__(self) -> None:
        self.validators: Set[str] = set()
        self.quorum_fraction: float = 0.67
        # proposal_id -> {txs, proposer, votes:set, ts, status}
        self.proposals: Dict[str, dict] = {}
        # simple rewards ledger
        self.rewards: Dict[str, float] = {}

    def has_quorum(self, votes: Set[str]) -> bool:
        n = max(1, len(self.validators))
        return len(votes) / n >= self.quorum_fraction


# ------------------------------------------------------------
# Core executor
# ------------------------------------------------------------
class WeAllExecutor:
    def __init__(self) -> None:
        self.path = _state_path()
        self.ledger: Dict[str, Any] = self._load_or_init_ledger()
        self.node_id: str = self._ensure_node_id()
        self.p2p = P2PManager()
        self.governance = GovernanceState()
        self.pool_split = {
            "validators": 0.25,
            "jurors": 0.25,
            "creators": 0.25,
            "storage": 0.10,
            "treasury": 0.15,
        }
        self.blocks_per_epoch = 100
        self.halving_interval_epochs = max(1, 210000 // self.blocks_per_epoch)

        self.cons = ConsensusState()
        self._bootstrap_consensus_from_config()

        self.current_block_height = len(self.ledger.get("chain", []))

    # ----------------------- persistence -----------------------
    def _load_or_init_ledger(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self._state_path_local()):
                with open(self._state_path_local(), "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data.setdefault("chain", [])
                        data.setdefault("mempool", [])
                        data.setdefault("events", [])
                        data.setdefault("balances", {})
                        data.setdefault("users", {})
                        data.setdefault("messages", {})
                        return data
        except Exception as e:
            log.warning(f"State load failed, fresh start: {e}")
        return {
            "chain": [],
            "mempool": [],
            "events": [],
            "balances": {},
            "users": {},
            "messages": {},
        }

    def _state_path_local(self) -> str:
        # indirection for easier testing
        return self.path

    def save_state(self) -> Dict[str, Any]:
        try:
            with open(self._state_path_local(), "w") as f:
                json.dump(self.ledger, f, indent=2, sort_keys=False)
        except Exception as e:
            log.error(f"Failed to save state: {e}")
        return {"ok": True}

    def load_state(self) -> Dict[str, Any]:
        self.ledger = self._load_or_init_ledger()
        self.current_block_height = len(self.ledger.get("chain", []))
        return {"ok": True, "height": self.current_block_height}

    # ----------------------- identity --------------------------
    def _ensure_node_id(self) -> str:
        nid = self.ledger.get("node_id")
        if not nid:
            nid = "node:" + uuid.uuid4().hex[:12]
            self.ledger["node_id"] = nid
            self.save_state()
        return nid

    # ----------------------- config / consensus bootstrap -------
    def _bootstrap_consensus_from_config(self) -> None:
        """
        Load validators & quorum from weall_config.yaml when available.
        Fallback: single-validator (this node) with quorum=1.0 (dev-friendly).
        """
        try:
            from weall_node.config import load_config
        except Exception:
            load_config = None

        if not load_config:
            self.cons.validators.add(self.node_id)
            self.cons.quorum_fraction = 1.0
            return

        try:
            cfg = load_config(repo_root=_repo_root()) or {}
            c = cfg.get("consensus", {})
            qf = c.get("quorum_fraction", 1.0)
            vals = c.get("validators") or []
            self.cons.quorum_fraction = float(qf)
            for v in vals:
                if isinstance(v, str) and v:
                    self.cons.validators.add(v)
            if not self.cons.validators:
                # default to self only if none set
                self.cons.validators.add(self.node_id)
            log.info(
                f"[consensus] validators={len(self.cons.validators)} quorum={self.cons.quorum_fraction}"
            )
        except Exception as e:
            log.warning(
                f"[consensus] config load failed ({e}); falling back to single-validator dev mode"
            )
            self.cons.validators.add(self.node_id)
            self.cons.quorum_fraction = 1.0

    # ----------------------- tx intake -------------------------
    def add_tx(self, payload: dict) -> Dict[str, Any]:
        self.ledger.setdefault("mempool", []).append(payload)
        return {"ok": True, "mempool_len": len(self.ledger["mempool"])}

    # ----------------------- consensus: propose/vote/finalize ---
    def propose_block(self, proposer_id: str) -> Dict[str, Any]:
        mem = self.ledger.setdefault("mempool", [])
        if not mem:
            return {"ok": False, "error": "mempool_empty"}
        txs = mem[:]
        mem.clear()
        pid = str(uuid.uuid4())
        votes: Set[str] = set()
        if proposer_id in self.cons.validators:
            votes.add(proposer_id)
        self.cons.proposals[pid] = {
            "txs": txs,
            "proposer": proposer_id,
            "votes": votes,
            "ts": _now(),
            "status": "proposed",
        }
        log.info(
            f"[consensus] proposed pid={pid} txs={len(txs)} proposer={proposer_id} votes={len(votes)}"
        )
        if self.cons.has_quorum(votes):
            self._finalize_block(pid)
        return {"ok": True, "proposal_id": pid, "tx_count": len(txs)}

    def vote_block(self, validator_id: str, proposal_id: str) -> Dict[str, Any]:
        if validator_id not in self.cons.validators:
            return {"ok": False, "error": "not_a_validator"}
        prop = self.cons.proposals.get(proposal_id)
        if not prop or prop.get("status") != "proposed":
            return {"ok": False, "error": "bad_proposal"}
        prop["votes"].add(validator_id)
        log.info(
            f"[consensus] vote pid={proposal_id} voter={validator_id} votes={len(prop['votes'])}"
        )
        if self.cons.has_quorum(prop["votes"]):
            self._finalize_block(proposal_id)
        return {"ok": True, "votes": len(prop["votes"])}

    # Back-compat alias
    def attest_block(self, validator_id: str, proposal_id: str) -> Dict[str, Any]:
        return self.vote_block(validator_id, proposal_id)

    def list_proposals(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for pid, p in self.cons.proposals.items():
            out[pid] = {
                "status": p.get("status"),
                "tx_count": len(p.get("txs", [])),
                "proposer": p.get("proposer"),
                "votes": sorted(list(p.get("votes", []))),
                "ts": p.get("ts"),
            }
        return out

    def _finalize_block(self, proposal_id: str) -> None:
        prop = self.cons.proposals.get(proposal_id)
        if not prop or prop.get("status") != "proposed":
            return
        chain = self.ledger.setdefault("chain", [])
        block = {
            "height": len(chain),
            "time": _now(),
            "txs": prop["txs"],
            "proposer": prop["proposer"],
            "votes": sorted(list(prop["votes"])),
        }
        self._apply_block(block)
        chain.append(block)
        prop["status"] = "committed"
        self._reward(block)
        self.save_state()
        self.current_block_height = len(chain)
        log.info(
            f"[consensus] committed height={block['height']} txs={len(block['txs'])}"
        )

    def _apply_block(self, block: dict) -> None:
        for tx in block.get("txs", []):
            try:
                self._apply_tx(tx)
            except Exception as e:
                log.exception(f"[apply] tx failed: {e}")

    def _apply_tx(self, tx: dict) -> None:
        """
        Minimal dispatcher that keeps API routes functional.
        If you have a richer runtime (process_tx), call it here.
        """
        # Hook to richer runtime if present
        if hasattr(self, "process_tx") and callable(getattr(self, "process_tx")):
            self.process_tx(tx)
            return

        # PoH events (used by poh.py)
        if "poh" in tx:
            poh = tx["poh"]
            tier = int(poh.get("tier", 0))
            tname = f"POH_TIER{tier}_VERIFY" if tier else "POH_EVENT"
            evt = {
                "type": tname,
                "user": poh.get("user"),
                "approved": True,
                "ts": _now(),
            }
            self.ledger.setdefault("events", []).append(evt)
            return

        # Transfers
        if "transfer" in tx:
            t = tx["transfer"]
            self._transfer_internal(t["sender"], t["recipient"], float(t["amount"]))
            return

        # Default generic event
        self.ledger.setdefault("events", []).append(
            {"type": "TX", "tx": tx, "ts": _now()}
        )

    def _reward(self, block: dict) -> None:
        prop = block.get("proposer")
        if prop:
            self.cons.rewards[prop] = self.cons.rewards.get(prop, 0.0) + 1.0
        for v in block.get("votes", []):
            self.cons.rewards[v] = self.cons.rewards.get(v, 0.0) + 0.25

    # ----------------- dev helper / legacy mining --------------
    def mine_block_dev(self) -> Dict[str, Any]:
        """
        Development convenience: propose → self-vote → finalize if this node is a validator.
        """
        res = self.propose_block(self.node_id)
        if not res.get("ok"):
            return res
        pid = res["proposal_id"]
        if self.node_id in self.cons.validators:
            self.vote_block(self.node_id, pid)
        return {"ok": True, "proposal_id": pid}

    def mine_block(self, *args, **kwargs) -> Dict[str, Any]:
        """
        LEGACY entrypoint: older code may call mine_block() (no args) or mine_block(payload).
        - If a payload dict is passed, enqueue it first, then dev-mine.
        """
        # Accept optional payload for backwards compatibility
        if args and isinstance(args[0], dict):
            self.add_tx(args[0])
        return self.mine_block_dev()

    def on_new_block(self, producer_id: str) -> Dict[str, Any]:
        """
        Compatibility for /block/new/{producer_id}: propose and self-vote if validator.
        """
        res = self.propose_block(producer_id)
        if res.get("ok") and producer_id in self.cons.validators:
            self.vote_block(producer_id, res["proposal_id"])
        return {"ok": True, "height": len(self.ledger.get("chain", []))}

    def simulate_blocks(self, n: int) -> Dict[str, Any]:
        """
        Compatibility: simulate n dev-mined blocks.
        """
        for _ in range(max(0, int(n))):
            self.mine_block_dev()
        return {"ok": True, "height": len(self.ledger.get("chain", []))}

    # ----------------------- balances --------------------------
    def balance(self, user: str) -> float:
        try:
            return float(self.ledger.setdefault("balances", {}).get(user, 0.0))
        except Exception:
            return 0.0

    def _transfer_internal(self, sender: str, recipient: str, amount: float) -> None:
        if amount <= 0:
            raise ValueError("amount_must_be_positive")
        bal = self.ledger.setdefault("balances", {})
        if sender != "treasury" and bal.get(sender, 0.0) < amount:
            raise ValueError("insufficient_funds")
        if sender != "treasury":
            bal[sender] = bal.get(sender, 0.0) - amount
        bal[recipient] = bal.get(recipient, 0.0) + amount

    def transfer(self, sender: str, recipient: str, amount: float) -> Dict[str, Any]:
        self.add_tx(
            {
                "transfer": {
                    "sender": sender,
                    "recipient": recipient,
                    "amount": float(amount),
                }
            }
        )
        return {"ok": True}

    def treasury_transfer(self, recipient: str, amount: float) -> Dict[str, Any]:
        self.add_tx(
            {
                "transfer": {
                    "sender": "treasury",
                    "recipient": recipient,
                    "amount": float(amount),
                }
            }
        )
        return {"ok": True}

    # ----------------------- users/messages --------------------
    def register_user(self, user_id: str, poh_level: int = 1) -> Dict[str, Any]:
        u = self.ledger.setdefault("users", {}).setdefault(user_id, {})
        u["poh_level"] = max(int(poh_level), int(u.get("poh_level", 0)))
        return {"ok": True, "user": user_id, "poh_level": u["poh_level"]}

    def add_friend(self, user_id: str, friend_id: str) -> Dict[str, Any]:
        u = self.ledger.setdefault("users", {}).setdefault(user_id, {})
        friends = u.setdefault("friends", [])
        if friend_id not in friends:
            friends.append(friend_id)
        return {"ok": True, "user": user_id, "friends": friends}

    def send_message(self, from_user: str, to_user: str, text: str) -> Dict[str, Any]:
        inbox = self.ledger.setdefault("messages", {}).setdefault(to_user, [])
        msg = {"from": from_user, "to": to_user, "text": str(text), "ts": _now()}
        inbox.append(msg)
        return {"ok": True, "message": msg}

    def read_messages(self, user: str) -> Dict[str, Any]:
        msgs = self.ledger.setdefault("messages", {}).get(user, [])
        return {"ok": True, "messages": msgs}

    # ----------------------- posts/comments --------------------
    def create_post(
        self, user_id: str, content: str, tags: List[str]
    ) -> Dict[str, Any]:
        posts = self.ledger.setdefault("posts", [])
        post = {
            "id": len(posts) + 1,
            "user": user_id,
            "content": content,
            "tags": tags,
            "ts": _now(),
        }
        posts.append(post)
        return {"ok": True, "post": post}

    def create_comment(
        self, user_id: str, post_id: int, content: str, tags: List[str]
    ) -> Dict[str, Any]:
        comments = self.ledger.setdefault("comments", [])
        com = {
            "id": len(comments) + 1,
            "user": user_id,
            "post_id": int(post_id),
            "content": content,
            "tags": tags,
            "ts": _now(),
        }
        comments.append(com)
        return {"ok": True, "comment": com}

    # ----------------------- governance ------------------------
    def create_proposal(
        self, title: str, description: str, amount: float
    ) -> Dict[str, Any]:
        p = {
            "id": len(self.governance.proposals),
            "title": title,
            "description": description,
            "amount": float(amount),
            "ts": _now(),
        }
        self.governance.proposals.append(p)
        return {"ok": True, "proposal": p}

    def cast_vote(self, user: str, proposal_id: int, vote: str) -> Dict[str, Any]:
        votes = self.ledger.setdefault("votes", {})
        pv = votes.setdefault(str(proposal_id), {})
        pv[str(user)] = str(vote)
        return {"ok": True, "proposal_id": proposal_id, "vote": vote}

    # ----------------------- admin knobs -----------------------
    def set_pool_split(self, split: Dict[str, float]) -> Dict[str, Any]:
        total = sum(float(v) for v in split.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError("split_must_sum_to_1")
        self.pool_split = {k: float(v) for k, v in split.items()}
        return {"ok": True, "pool_split": self.pool_split}

    def set_blocks_per_epoch(self, bpe: int) -> Dict[str, Any]:
        self.blocks_per_epoch = max(1, int(bpe))
        return {"ok": True}

    def set_halving_interval_epochs(self, epochs: int) -> Dict[str, Any]:
        self.halving_interval_epochs = max(1, int(epochs))
        return {"ok": True}

    # ----------------------- health/metrics --------------------
    def get_health(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "height": len(self.ledger.get("chain", [])),
            "mempool": len(self.ledger.get("mempool", [])),
            "validators": len(self.cons.validators),
        }

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "height": len(self.ledger.get("chain", [])),
            "mempool_len": len(self.ledger.get("mempool", [])),
            "balances_count": len(self.ledger.get("balances", {})),
            "messages_count": sum(
                len(v) for v in self.ledger.get("messages", {}).values()
            ),
            "events_count": len(self.ledger.get("events", [])),
            "validator_count": len(self.cons.validators),
            "rewards": self.cons.rewards,
        }


# ------------------------------------------------------------
# Facade for API modules (keeps surface stable)
# ------------------------------------------------------------
class _ExecFacade:
    def __init__(self, impl: WeAllExecutor) -> None:
        self.exec = impl

    # attribute passthroughs used directly
    @property
    def ledger(self):
        return self.exec.ledger

    @property
    def node_id(self):
        return self.exec.node_id

    @property
    def p2p(self):
        return self.exec.p2p

    # persistence
    def save_state(self):
        return self.exec.save_state()

    def load_state(self):
        return self.exec.load_state()

    # consensus (new + legacy)
    def add_tx(self, payload: dict):
        return self.exec.add_tx(payload)

    def propose_block(self, proposer_id: str):
        return self.exec.propose_block(proposer_id)

    def vote_block(self, validator_id: str, proposal_id: str):
        return self.exec.vote_block(validator_id, proposal_id)

    def attest_block(self, validator_id: str, proposal_id: str):
        return self.exec.attest_block(validator_id, proposal_id)  # alias

    def list_proposals(self):
        return self.exec.list_proposals()

    def mine_block(self, *args, **kwargs):
        return self.exec.mine_block(*args, **kwargs)

    def mine_block_dev(self):
        return self.exec.mine_block_dev()

    def on_new_block(self, producer_id: str):
        return self.exec.on_new_block(producer_id)

    def simulate_blocks(self, n: int):
        return self.exec.simulate_blocks(n)

    # functional APIs used by routes
    def balance(self, user_id: str) -> float:
        return self.exec.balance(user_id)

    def transfer(self, sender: str, recipient: str, amount: float):
        return self.exec.transfer(sender, recipient, amount)

    def treasury_transfer(self, recipient: str, amount: float):
        return self.exec.treasury_transfer(recipient, amount)

    def register_user(self, user_id: str, poh_level: int = 1):
        return self.exec.register_user(user_id, poh_level)

    def add_friend(self, user_id: str, friend_id: str):
        return self.exec.add_friend(user_id, friend_id)

    def send_message(self, from_user: str, to_user: str, text: str):
        return self.exec.send_message(from_user, to_user, text)

    def read_messages(self, user: str):
        return self.exec.read_messages(user)

    def create_post(self, user_id: str, content: str, tags: List[str]):
        return self.exec.create_post(user_id, content, tags)

    def create_comment(self, user_id: str, post_id: int, content: str, tags: List[str]):
        return self.exec.create_comment(user_id, post_id, content, tags)

    def create_proposal(self, title: str, description: str, amount: float):
        return self.exec.create_proposal(title, description, amount)

    def cast_vote(self, user: str, proposal_id: int, vote: str):
        return self.exec.cast_vote(user, proposal_id, vote)

    def set_pool_split(self, split: Dict[str, float]):
        return self.exec.set_pool_split(split)

    def set_blocks_per_epoch(self, bpe: int):
        return self.exec.set_blocks_per_epoch(bpe)

    def set_halving_interval_epochs(self, epochs: int):
        return self.exec.set_halving_interval_epochs(epochs)

    def get_health(self):
        return self.exec.get_health()

    def get_metrics(self):
        return self.exec.get_metrics()


# ------------------------------------------------------------
# Module-level singleton facade (what API modules import)
# ------------------------------------------------------------
_EXEC_INSTANCE = WeAllExecutor()
executor = _ExecFacade(_EXEC_INSTANCE)
