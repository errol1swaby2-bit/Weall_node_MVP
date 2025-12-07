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
import hashlib
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


def _block_hash(header: dict) -> str:
    """Return a deterministic SHA-256 block id from a block header."""
    # ensure deterministic JSON payload across nodes
    payload = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    def mine_block(self, payload: Optional[dict] = None) -> Dict[str, Any]:
        """
        DEV helper: mine a single block in a single-node environment.

        Keeps older API calls like `executor.mine_block()` working by:
        - Optionally enqueuing `payload` into the mempool
        - Ensuring the local node_id is a validator
        - Proposing a block
        - Self-voting to reach quorum and finalize
        """
        # Optionally push a tx into the mempool
        if payload:
            try:
                self.add_tx(payload)
            except Exception:
                # Extremely defensive: fall back to raw mempool access
                self.ledger.setdefault("mempool", []).append(payload)

        # Ensure this node is treated as a validator for local dev
        node_id = getattr(self, "node_id", "local")
        try:
            self.cons.validators.add(node_id)
        except Exception:
            return {"ok": False, "error": "consensus_unavailable"}

        # Propose a block with pending txs
        res = self.propose_block(node_id)
        if not res.get("ok"):
            return res

        proposal_id = res.get("proposal_id")
        if not proposal_id:
            return {"ok": False, "error": "no_proposal_id"}

        # Self-vote to finalize in a single-node context
        vres = self.vote_block(node_id, proposal_id)
        if not vres.get("ok"):
            return vres

        chain = self.ledger.get("chain") or []
        block = chain[-1] if chain else None
        return {
            "ok": True,
            "block": block,
            "proposal_id": proposal_id,
            "votes": vres.get("votes"),
        }

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

        # Epoch / tokenomics runtime (WeCoin) + genesis / GSM params
        self.current_epoch: int = 0
        # Will be overridden by genesis if present
        self.bootstrap_mode: bool = False
        self.min_validators: int = 0

        try:
            from weall_node.weall_runtime.ledger import WeCoinLedger
            self.wecoin = WeCoinLedger()
        except Exception:
            # Soft-fail: keep node running even if tokenomics runtime is missing
            self.wecoin = None  # type: ignore[assignment]

        # Load genesis / GSM settings if available
        try:
            from weall_node.consensus.params import load_genesis_params
            self.genesis = load_genesis_params()
        except Exception:
            self.genesis = {}

        g = self.genesis or {}
        # GSM / bootstrap mode
        self.bootstrap_mode = bool(g.get("gsm_active", False))
        self.min_validators = int(g.get("min_validators", 0) or 0)

        # Allow genesis to override blocks_per_epoch
        g_bpe = g.get("blocks_per_epoch")
        if g_bpe:
            try:
                self.blocks_per_epoch = int(g_bpe)
            except Exception:
                pass

        # Apply pool split to WeCoin runtime, if configured
        g_split = g.get("pool_split") or {}
        if g_split:
            try:
                self.set_pool_split(g_split)
            except Exception:
                pass

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
        prev_block_id = (
            chain[-1].get("block_id")
            if chain and isinstance(chain[-1], dict)
            else None
        )
        height = len(chain)
        votes = sorted(list(prop["votes"]))
        header = {
            "height": height,
            "time": _now(),
            "proposer": prop["proposer"],
            "votes": votes,
            "prev_block_id": prev_block_id,
        }
        block_id = _block_hash(header)
        block = {
            "block_id": block_id,
            **header,
            "txs": prop["txs"],
        }
        self._apply_block(block)
        chain.append(block)
        prop["status"] = "committed"
        self._reward(block)
        self.save_state()
        self.current_block_height = len(chain)

        # Epoch advancement + WeCoin rewards (if configured)
        try:
            blocks_per_epoch = int(getattr(self, "blocks_per_epoch", 0) or 0)
        except Exception:
            blocks_per_epoch = 0
        if blocks_per_epoch > 0:
            # heights are zero-based; use height+1 when checking epoch boundary
            if (block["height"] + 1) % blocks_per_epoch == 0:
                # Initialize for older state files if missing
                if not hasattr(self, "current_epoch"):
                    self.current_epoch = 0  # type: ignore[attr-defined]
                self.current_epoch += 1  # type: ignore[attr-defined]

                winners = {}
                epoch_reward = None
                wecoin = getattr(self, "wecoin", None)
                if wecoin is not None and hasattr(wecoin, "distribute_epoch_rewards"):
                    try:
                        bootstrap_mode = bool(getattr(self, "bootstrap_mode", False))
                        winners = wecoin.distribute_epoch_rewards(  # type: ignore[call-arg]
                            int(self.current_epoch),
                            bootstrap_mode=bootstrap_mode,
                        )
                        if hasattr(wecoin, "current_epoch_reward"):
                            epoch_reward = wecoin.current_epoch_reward()
                    except Exception as e:
                        log.warning("Epoch reward distribution failed: %s", e)

                events = self.ledger.setdefault("events", [])
                events.append(
                    {
                        "type": "epoch",
                        "epoch": int(getattr(self, "current_epoch", 0)),
                        "block_height": int(block["height"]),
                        "winners": winners,
                        "epoch_reward": epoch_reward,
                        "ts": _now(),
                    }
                )

        # Check whether GSM (bootstrap mode) should expire
        try:
            self._check_gsm_expiry(block)
        except Exception as e:
            log.warning("Failed GSM expiry check: %s", e)

        # Apply WeCoin block rewards (per-block lottery across all pools)
        core = getattr(self, "exec", self)
        wecoin = getattr(core, "wecoin", None)
        if wecoin is not None and hasattr(wecoin, "distribute_block_rewards"):
            try:
                height = int(block.get("height", 0))
                genesis = getattr(self, "genesis", {}) or {}
                blocks_per_epoch = int(genesis.get("blocks_per_epoch") or 100)
                epoch = height // max(1, blocks_per_epoch)
                wecoin.distribute_block_rewards(
                    block_height=height,
                    epoch=epoch,
                    blocks_per_epoch=blocks_per_epoch,
                    bootstrap_mode=getattr(self, "bootstrap_mode", False),
                )
            except Exception as e:
                log.warning("WeCoin block reward distribution failed: %s", e)

        log.info(
            f"[consensus] committed height={block['height']} txs={len(block['txs'])} id={block_id}"
        )

    def apply_remote_block(self, block: dict) -> Dict[str, Any]:
        """
        Integrate a block received from a peer.

        Genesis assumptions:
        - We are in a single-epoch, single-fork environment.
        - We only accept blocks that extend the current tip by exactly +1 height.
        - We verify the block_id against the deterministic header hash.
        - We reject or ignore anything that doesn't cleanly extend the local chain.

        Returns a dict of the shape:
            {
              "ok": bool,
              "status": "appended" | "ignored",
              "error": <str> | None,
              "height": <int> | None
            }
        """
        try:
            if not isinstance(block, dict):
                return {
                    "ok": False,
                    "status": "ignored",
                    "error": "invalid_block_type",
                    "height": None,
                }

            chain = self.ledger.setdefault("chain", [])
            local_height = len(chain)

            # Basic required fields
            height = block.get("height")
            prev_block_id = block.get("prev_block_id")
            block_id = block.get("block_id")

            if height is None or block_id is None:
                return {
                    "ok": False,
                    "status": "ignored",
                    "error": "missing_fields",
                    "height": local_height,
                }

            # Recompute header hash to validate block_id (header = non-tx fields)
            header = {k: v for k, v in block.items() if k not in ("block_id", "txs")}
            computed_id = _block_hash(header)
            if str(block_id) != computed_id:
                return {
                    "ok": False,
                    "status": "ignored",
                    "error": "bad_block_hash",
                    "height": local_height,
                }

            # For Genesis, only accept the next sequential block:
            #   remote.height == local_height
            if height != local_height:
                # If the remote chain is strictly behind, or skipping heights,
                # we ignore it for now (no fork handling in Genesis).
                return {
                    "ok": False,
                    "status": "ignored",
                    "error": "height_mismatch",
                    "height": local_height,
                }

            # Validate prev_block_id if we already have a tip
            if local_height > 0:
                tip = chain[-1]
                tip_id = tip.get("block_id")
                if tip_id != prev_block_id:
                    return {
                        "ok": False,
                        "status": "ignored",
                        "error": "prev_block_mismatch",
                        "height": local_height,
                    }

            # At this point we treat the block as valid and append it.
            self._apply_block(block)
            chain.append(block)
            self.current_block_height = len(chain)
            try:
                self.save_state()
            except Exception:
                # Not fatal for Genesis; chain has already been updated in-memory.
                pass

            return {
                "ok": True,
                "status": "appended",
                "error": None,
                "height": self.current_block_height,
            }
        except Exception as e:
            # Extremely defensive catch-all so that remote blocks can never
            # crash the node.
            try:
                current_height = len(self.ledger.get("chain", []))
            except Exception:
                current_height = None
            return {
                "ok": False,
                "status": "ignored",
                "error": f"exception:{e!s}",
                "height": current_height,
            }

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

    # ------------------------------------------------------------
    # WEC balance + transfer helpers
    # ------------------------------------------------------------
    def _ensure_balance_map(self) -> dict:
        """
        Ensure self.ledger has a 'balances' dict and return it.

        This is our canonical per-user WEC balance store at the executor
        level, with optional compatibility for older 'accounts' maps.
        """
        led = getattr(self, "ledger", None)
        if led is None:
            led = {}
            self.ledger = led

        balances = led.get("balances")
        if not isinstance(balances, dict):
            balances = {}
            led["balances"] = balances

        return balances

    def get_balance(self, user_id: str) -> float:
        """
        Return the current WEC balance for a user.

        Falls back to legacy ledger['accounts'] if 'balances' doesn't
        have an entry yet.
        """
        user_id = (user_id or "").strip()
        if not user_id:
            return 0.0

        balances = self._ensure_balance_map()
        bal = balances.get(user_id, None)

        # Back-compat with older 'accounts' dict, if present
        if bal is None:
            try:
                accounts = self.ledger.get("accounts") or {}
                bal = accounts.get(user_id, 0.0)
            except Exception:
                bal = 0.0

        try:
            return float(bal)
        except Exception:
            return 0.0

    def _set_balance(self, user_id: str, amount: float) -> None:
        """
        Internal helper: set a user's WEC balance.

        Writes into ledger['balances'] only; if you later add a dedicated
        WeCoin runtime, you can mirror into that here as well.
        """
        user_id = (user_id or "").strip()
        if not user_id:
            return

        balances = self._ensure_balance_map()
        try:
            balances[user_id] = float(amount)
        except Exception:
            balances[user_id] = 0.0

    def credit(self, user_id: str, amount: float) -> float:
        """
        Increase a user's balance by `amount`. Returns the new balance.

        This is a trusted dev-only "mint" at the moment.
        """
        user_id = (user_id or "").strip()
        if not user_id:
            return 0.0

        try:
            amount = float(amount)
        except Exception:
            return self.get_balance(user_id)

        if amount <= 0:
            return self.get_balance(user_id)

        new_balance = self.get_balance(user_id) + amount
        self._set_balance(user_id, new_balance)

        try:
            self.save_state()
        except Exception:
            pass

        return new_balance

    def debit(self, user_id: str, amount: float) -> float:
        """
        Decrease a user's balance by `amount`.

        Raises ValueError on insufficient funds. Returns new balance.
        """
        user_id = (user_id or "").strip()
        if not user_id:
            return 0.0

        try:
            amount = float(amount)
        except Exception:
            return self.get_balance(user_id)

        if amount <= 0:
            return self.get_balance(user_id)

        bal = self.get_balance(user_id)
        if bal < amount:
            raise ValueError("insufficient_funds")

        new_balance = bal - amount
        self._set_balance(user_id, new_balance)

        try:
            self.save_state()
        except Exception:
            pass

        return new_balance

    def transfer_wec(self, from_id: str, to_id: str, amount: float) -> dict:
        """
        Simple single-node WEC transfer.

        This is a trusted executor call for now (no signatures). Later we
        can upgrade it to build a tx and push it into the mempool.
        """
        from_id = (from_id or "").strip()
        to_id = (to_id or "").strip()

        # Basic parameter validation
        if not from_id or not to_id:
            return {"ok": False, "error": "invalid_transfer_params"}
        if from_id == to_id:
            return {"ok": False, "error": "cannot_send_to_self"}

        try:
            amount = float(amount)
        except Exception:
            return {"ok": False, "error": "invalid_amount"}

        if amount <= 0:
            return {"ok": False, "error": "amount_must_be_positive"}

        # Debit then credit
        try:
            self.debit(from_id, amount)
        except ValueError:
            return {"ok": False, "error": "insufficient_funds"}
        except Exception as e:
            return {"ok": False, "error": f"debit_failed:{e!s}"}

        try:
            self.credit(to_id, amount)
        except Exception as e:
            # Best-effort rollback: put funds back on sender
            try:
                self.credit(from_id, amount)
            except Exception:
                pass
            return {"ok": False, "error": f"credit_failed:{e!s}"}

        return {
            "ok": True,
            "from": from_id,
            "to": to_id,
            "amount": float(amount),
            "from_balance": self.get_balance(from_id),
            "to_balance": self.get_balance(to_id),
        }

    def _reward(self, block: dict) -> None:
        prop = block.get("proposer")
        if prop:
            self.cons.rewards[prop] = self.cons.rewards.get(prop, 0.0) + 1.0
        for v in block.get("votes", []):
            self.cons.rewards[v] = self.cons.rewards.get(v, 0.0) + 0.25

        # Mirror consensus rewards into WeCoin validator tickets
        wecoin = getattr(self, "wecoin", None)
        if wecoin is not None and hasattr(wecoin, "add_ticket"):
            try:
                if prop:
                    wecoin.add_ticket("validators", prop, weight=1.0)
                for v in block.get("votes", []):
                    wecoin.add_ticket("validators", v, weight=0.25)
            except Exception as e:
                log.warning("Failed to record validator tickets for epoch rewards: %s", e)

    # ----------------- dev helper / legacy mining --------------


class _ExecFacade:
    """
    Lightweight facade around a WeAllExecutor instance.

    - Exposes the core executor as .exec
    - Delegates attribute access to the underlying executor so existing
      code can use either executor.<attr> or executor.exec.<attr>.
    """

    def __init__(self, core):
        self.exec = core

    def __getattr__(self, name):
        return getattr(self.exec, name)


# Global singleton used everywhere
executor = _ExecFacade(WeAllExecutor())
