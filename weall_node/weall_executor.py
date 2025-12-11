# weall_node/weall_executor.py
"""
WeAll Executor — unified runtime with quorum finalization + dev mining (PBFT-lite)

This merges the “toy finality” flow and the production-leaning quorum flow:
- DEV MINE (legacy): executor.mine_block([optional_payload]) → propose→self-vote→finalize
- QUORUM: propose_block(proposer_id) + vote_block(validator_id, proposal_id) → finalize on quorum
- Legacy/alias: attest_block(validator_id, proposal_id) == vote_block(...)

Back-compat: keeps prior method names & attribute access used by API modules (PoH, ledger, etc.).

Extended with NodeKind topology:
- NodeKind controls whether this node is allowed to participate in consensus.
- Non-VALIDATOR_NODE kinds can still sync and apply remote blocks but cannot
  propose or vote on blocks.
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

from . import node_config
from .weall_runtime import roles as runtime_roles

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
    """
    Return a deterministic SHA-256 block id from a block header.

    We canonicalize the JSON representation to ensure the same header yields
    the same block id on every node.
    """
    payload = json.dumps(
        header,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class GovernanceState:
    """
    GovernanceState is a simple container for in-memory governance related
    information.

    The canonical governance state (proposals, votes, params) lives in
    executor.ledger["governance"] and is persisted to weall_state.json;
    this dataclass is mostly a convenience placeholder for future in-memory
    cache structures.
    """

    proposals: List[Dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------
# Consensus state (PBFT-lite / PoA-lite)
# ------------------------------------------------------------
class ConsensusState:
    """
    Lightweight PoA/PBFT-ish consensus helper.

    This is NOT a full production consensus engine. It's a simple mechanism
    for:
    - tracking validators
    - opening proposals (sets of txs)
    - collecting votes
    - deciding when a proposal has reached quorum

    Block construction / application are managed by WeAllExecutor itself.
    """

    def __init__(self) -> None:
        self.validators: Set[str] = set()
        self.quorum_fraction: float = 0.67
        # proposal_id -> {txs, proposer, votes:set, ts, status}
        self.proposals: Dict[str, dict] = {}
        # simple rewards ledger (internal; not the same as WeCoin)
        self.rewards: Dict[str, float] = {}

    # ----------------------- validators / quorum ---------------
    def set_validators(self, validators: List[str]) -> None:
        self.validators = set(validators or [])

    def set_quorum_fraction(self, fraction: float) -> None:
        try:
            self.quorum_fraction = max(0.0, min(1.0, float(fraction)))
        except Exception:
            self.quorum_fraction = 0.67

    def is_validator(self, node_id: str) -> bool:
        return node_id in self.validators

    def has_quorum(self, votes: Set[str]) -> bool:
        if not self.validators:
            return False
        participating = self.validators & votes
        if not participating:
            return False
        frac = len(participating) / float(len(self.validators))
        return frac >= self.quorum_fraction

    # ----------------------- proposals / voting ----------------
    def open_proposal(self, proposer_id: str, txs: List[dict]) -> str:
        proposal_id = uuid.uuid4().hex[:16]
        self.proposals[proposal_id] = {
            "id": proposal_id,
            "proposer": proposer_id,
            "txs": list(txs or []),
            "votes": set(),
            "status": "open",
            "ts": _now(),
        }
        return proposal_id

    def vote(self, validator_id: str, proposal_id: str) -> dict:
        if proposal_id not in self.proposals:
            raise ValueError(f"unknown_proposal:{proposal_id}")
        p = self.proposals[proposal_id]
        if p["status"] != "open":
            raise ValueError(f"proposal_not_open:{proposal_id}")
        if validator_id not in self.validators:
            raise ValueError(f"not_validator:{validator_id}")
        p["votes"].add(validator_id)
        return {
            "proposal_id": proposal_id,
            "votes": list(sorted(p["votes"])),
            "has_quorum": self.has_quorum(p["votes"]),
        }

    def finalize_if_quorum(self, proposal_id: str) -> Optional[dict]:
        """
        If the proposal has reached quorum, mark it finalized and return the
        proposal record. Otherwise, return None.
        """
        p = self.proposals.get(proposal_id)
        if not p:
            return None
        if p["status"] != "open":
            return None
        if not self.has_quorum(p["votes"]):
            return None
        p["status"] = "finalized"
        return p

    # ----------------------- simple rewards ledger ------------
    def credit_reward(self, validator_id: str, amount: float) -> None:
        if amount <= 0:
            return
        self.rewards[validator_id] = self.rewards.get(validator_id, 0.0) + float(amount)


# ------------------------------------------------------------
# P2P / sync stubs (placeholder for future gossip implementation)
# ------------------------------------------------------------
class P2PManager:
    """
    Placeholder for eventual P2P/gossip implementation.

    For now this is just a stub used by the executor so that the public API
    shape is in place for future multi-node networking.
    """

    def __init__(self) -> None:
        self.peers: Dict[str, dict] = {}

    def register_peer(self, node_id: str, meta: dict) -> None:
        self.peers[node_id] = dict(meta or {})

    def get_peers(self) -> Dict[str, dict]:
        return dict(self.peers)


# ------------------------------------------------------------
# Main Executor
# ------------------------------------------------------------
class WeAllExecutor:
    """
    Unified executor for:

    - Applying transactions to the logical ledger
    - Managing a simple PBFT-lite / PoA-lite consensus flow
    - Exposing helper methods used by API modules (poh, governance, etc.)

    In production terms this is a "reference node" implementation rather than
    a fully-hardened validator client.
    """

    # ----------------------- core init / state -----------------
    def __init__(self) -> None:
        self.path = _state_path()
        self.ledger: Dict[str, Any] = self._load_or_init_ledger()
        self.node_id: str = self._ensure_node_id()
        # Operator identity (can be overridden by config; defaults to node_id)
        self.operator_id: str = self.node_id
        self.p2p = P2PManager()
        self.governance = GovernanceState()
        # Reward pool split (mirrors weall_runtime.ledger.DEFAULT_POOL_SPLIT)
        # 20% each to validators / jurors / creators / operators / treasury.
        self.pool_split = {
            "validators": 0.20,
            "jurors": 0.20,
            "creators": 0.20,
            "operators": 0.20,
            "treasury": 0.20,
        }
        self.blocks_per_epoch = 100
        self.halving_interval_epochs = max(1, 210000 // self.blocks_per_epoch)

        self.cons = ConsensusState()
        self._bootstrap_consensus_from_config()

        # Node topology / kind (observer_client, public_gateway, validator_node, community_node)
        self.node_kind: runtime_roles.NodeKind = node_config.NODE_KIND

        # Epoch / tokenomics runtime (WeCoin) + genesis / GSM params
        self.current_epoch: int = 0
        # Will be overridden by genesis if present
        self.bootstrap_mode: bool = False
        self.min_validators: int = 0

        # WeCoin runtime
        try:
            from weall_node.weall_runtime.ledger import WeCoinLedger

            self.wecoin = WeCoinLedger()
        except Exception as e:
            log.warning("WeCoinLedger unavailable: %s", e)
            self.wecoin = None

        # Load genesis / GSM settings if available
        try:
            from weall_node.consensus.params import load_genesis_params

            self.genesis = load_genesis_params()
        except Exception as e:
            log.warning("Failed to load genesis params: %s", e)
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

    def set_pool_split(self, split: Dict[str, float]) -> None:
        """Update the reward pool split and keep it in sync with the WeCoin runtime.

        Fractions are normalized to sum to 1.0 to avoid configuration errors.
        If the WeCoin runtime exposes a set_pool_split() method, we delegate to it;
        otherwise we just update the executor's cached pool_split.
        """
        total = float(sum(split.values())) or 1.0
        normalized = {k: float(v) / total for k, v in split.items()}

        wecoin = getattr(self, "wecoin", None)
        if wecoin is not None and hasattr(wecoin, "set_pool_split"):
            try:
                wecoin.set_pool_split(normalized)  # type: ignore[attr-defined}
                self.pool_split = dict(getattr(wecoin, "pool_split", normalized))
                return
            except Exception:
                # If runtime update fails for any reason, fall back to local-only update.
                pass

        self.pool_split = normalized

    # ----------------------- node topology helpers -------------
    def can_participate_in_consensus(self) -> bool:
        """
        True if this node is configured as a validator node.

        Used to guard block production / consensus steps.
        """
        return self.node_kind == runtime_roles.NodeKind.VALIDATOR_NODE

    def node_topology_profile(self) -> dict:
        """
        Return a JSON-friendly description of this node's configured role.

        This is used by the /node/meta API endpoint to tell the frontend
        what kind of node it's talking to.
        """
        profile = runtime_roles.node_topology_profile(self.node_kind)
        return {
            "kind": profile.kind.value,
            "exposes_public_api": profile.exposes_public_api,
            "participates_in_consensus": profile.participates_in_consensus,
            "stores_group_data": profile.stores_group_data,
            "is_private_scope": profile.is_private_scope,
            "node_id": self.node_id,
        }

    # ----------------------- ledger IO -------------------------
    def _load_or_init_ledger(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {
                "accounts": {},
                "chain": [],
                "events": [],
            }
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Failed to load state; starting fresh: %s", e)
            return {
                "accounts": {},
                "chain": [],
                "events": [],
            }

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.ledger, f, indent=2, sort_keys=False)

    # ----------------------- node_id helpers -------------------
    def _ensure_node_id(self) -> str:
        nid = self.ledger.get("node_id")
        if not nid:
            nid = uuid.uuid4().hex[:16]
            self.ledger["node_id"] = nid
            self.save_state()
        return nid

    # ----------------------- mempool helpers -------------------
    def add_tx(self, payload: dict) -> Dict[str, Any]:
        """
        Add a transaction payload to the local mempool.

        This does not execute the transaction; it just queues it up to be
        included in the next proposed block.
        """
        self.ledger.setdefault("mempool", []).append(payload)
        return {"ok": True, "mempool_len": len(self.ledger["mempool"])}

    def drain_mempool(self) -> List[dict]:
        mem = self.ledger.setdefault("mempool", [])
        txs = list(mem)
        mem.clear()
        return txs

    # ----------------------- block helpers ---------------------
    def _build_block(self, txs: List[dict]) -> dict:
        chain = self.ledger.setdefault("chain", [])
        height = len(chain)
        prev = chain[-1]["id"] if chain else None
        header = {
            "height": height,
            "prev_id": prev,
            "ts": _now(),
            "txs_root": hashlib.sha256(
                json.dumps(txs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        block_id = _block_hash(header)
        block = {
            "id": block_id,
            "height": height,
            "header": header,
            "txs": txs,
        }
        return block

    def _apply_block(self, block: dict) -> None:
        """
        Apply a block's transactions to the ledger.

        This method should apply each tx in order and update:
        - balances
        - governance state
        - poh state
        - reputation
        - etc.

        For now, this remains a placeholder and only appends the block
        to the chain. The higher-level modules (poh, governance, disputes)
        operate directly on executor.ledger and are responsible for the
        actual business logic mutations.
        """
        chain = self.ledger.setdefault("chain", [])
        block_id = block.get("id")
        height = block.get("height", len(chain))

        # Very simple "extend only" rule
        if chain:
            tip = chain[-1]
            if height != tip["height"] + 1:
                log.warning(
                    "rejecting block that does not extend tip: tip=%s, new_height=%s",
                    tip["height"],
                    height,
                )
                return
            if block["header"]["prev_id"] != tip["id"]:
                log.warning(
                    "rejecting block with mismatched prev_id: tip=%s, prev_id=%s",
                    tip["id"],
                    block["header"]["prev_id"],
                )
                return
            # verify hash
            expected = _block_hash(block["header"])
            if expected != block_id:
                log.warning(
                    "rejecting block with invalid id: expected=%s, got=%s",
                    expected,
                    block_id,
                )
                return
        else:
            # First block: just accept if header hash matches id
            expected = _block_hash(block["header"])
            if expected != block_id:
                log.warning(
                    "rejecting genesis block with invalid id: expected=%s, got=%s",
                    expected,
                    block_id,
                )
                return

        # Append block
        chain.append(block)
        self.current_block_height = len(chain)

    # ----------------------- reward ticket helpers -------------
    def _issue_block_tickets(self, block: dict, proposal: Optional[dict] = None) -> None:
        """
        Issue WeCoin tickets for this finalized block:

        - validators pool: proposal proposer (or block/header fallback, or node_id)
        - operators pool: this node's operator_id (defaults to node_id)

        This does NOT mint coins; it only adjusts tickets. Actual WCN rewards
        are handled by the WeCoinLedger in weall_runtime/ledger.py.
        """
        wecoin = getattr(self, "wecoin", None)
        if wecoin is None or not hasattr(wecoin, "add_ticket"):
            return

        header = block.get("header") or {}

        proposer = None
        if proposal:
            proposer = proposal.get("proposer")

        proposer = (
            proposer
            or block.get("proposer")
            or header.get("proposer")
            or header.get("proposer_id")
            or self.node_id
        )

        if proposer:
            try:
                wecoin.add_ticket("validators", proposer, weight=1.0)
            except Exception:
                log.warning(
                    "Failed to add validator ticket for %s", proposer, exc_info=True
                )

        operator_id = getattr(self, "operator_id", None) or self.node_id
        if operator_id:
            try:
                wecoin.add_ticket("operators", operator_id, weight=1.0)
            except Exception:
                log.warning(
                    "Failed to add operator ticket for %s", operator_id, exc_info=True
                )

    def add_creator_ticket(self, creator_id: str, weight: float = 1.0) -> None:
        """
        Public helper for content modules to record creator rewards.

        Does not mint coins; just records a ticket in the 'creators' pool.
        """
        if not creator_id:
            return
        if weight <= 0:
            return
        wecoin = getattr(self, "wecoin", None)
        if wecoin is None or not hasattr(wecoin, "add_ticket"):
            return
        try:
            wecoin.add_ticket("creators", creator_id, weight=float(weight))
        except Exception:
            log.warning(
                "Failed to add creator ticket for %s", creator_id, exc_info=True
            )

    # ----------------------- consensus bootstrap ---------------
    def _bootstrap_consensus_from_config(self) -> None:
        """
        Initialize the ConsensusState (validators, quorum) from node_config.

        This reads any static validator list / quorum overrides from
        weall_node/node_config.py.
        """
        validators = getattr(node_config, "VALIDATORS", []) or []
        quorum = getattr(node_config, "QUORUM_FRACTION", 0.67)
        self.cons.set_validators(validators)
        self.cons.set_quorum_fraction(quorum)

    # ----------------------- block production API --------------
    def propose_block(self, proposer_id: str) -> Dict[str, Any]:
        """
        Open a new consensus proposal using current mempool txs.

        This is the first step of the quorum-based consensus flow.
        """
        if not self.can_participate_in_consensus():
            raise ValueError("node_not_validator")

        if not self.cons.is_validator(proposer_id):
            raise ValueError("not_validator")

        txs = self.drain_mempool()
        block = self._build_block(txs)
        proposal_id = self.cons.open_proposal(proposer_id, txs)
        # Attach block header so that finalization can commit it.
        block["proposal_id"] = proposal_id
        self.ledger.setdefault("pending_blocks", {})[proposal_id] = block
        return {
            "ok": True,
            "proposal_id": proposal_id,
            "block_id": block["id"],
            "height": block["height"],
            "txs_len": len(txs),
        }

    def vote_block(self, validator_id: str, proposal_id: str) -> Dict[str, Any]:
        """
        Cast a vote on a proposal and finalize the block if quorum is reached.
        """
        if not self.can_participate_in_consensus():
            raise ValueError("node_not_validator")

        vres = self.cons.vote(validator_id, proposal_id)
        if vres["has_quorum"]:
            finalized = self.cons.finalize_if_quorum(proposal_id)
            if finalized:
                return self._commit_finalized_block(proposal_id, finalized)
        return {
            "ok": True,
            "proposal_id": proposal_id,
            "has_quorum": vres["has_quorum"],
            "votes": vres.get("votes"),
        }

    def attest_block(self, validator_id: str, proposal_id: str) -> Dict[str, Any]:
        """
        Legacy alias for vote_block, kept for older API modules.
        """
        return self.vote_block(validator_id, proposal_id)

    def _commit_finalized_block(self, proposal_id: str, proposal: dict) -> Dict[str, Any]:
        pending_blocks = self.ledger.setdefault("pending_blocks", {})
        block = pending_blocks.pop(proposal_id, None)
        if not block:
            raise ValueError(f"missing_pending_block:{proposal_id}")

        chain = self.ledger.get("chain") or []
        height = len(chain)
        block_id = block.get("id")
        block["height"] = height
        block["header"]["height"] = height
        block["header"]["prev_id"] = chain[-1]["id"] if chain else None

        # Check header hash matches id
        expected = _block_hash(block["header"])
        if expected != block_id:
            log.warning(
                "refusing to commit block with mismatched id: expected=%s, got=%s",
                expected,
                block_id,
            )
            raise ValueError("invalid_block_hash")

        # Apply the block to the ledger
        self._apply_block(block)
        self.save_state()

        # Check whether GSM (bootstrap mode) should expire
        try:
            self._check_gsm_expiry(block)
        except Exception as e:
            log.warning("Failed GSM expiry check: %s", e)

        # Issue validator/operator tickets based on this finalized block
        try:
            self._issue_block_tickets(block, proposal)
        except Exception as e:
            log.warning("Block ticket wiring failed: %s", e)

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

        return {
            "ok": True,
            "block": block,
            "proposal_id": proposal_id,
            "votes": proposal.get("votes"),
        }

    def apply_remote_block(self, block: dict) -> Dict[str, Any]:
        """
        Apply a block received from another node.

        This bypasses local consensus and is intended for syncing followers.

        Genesis assumptions:
        - We are in a single-epoch, single-fork environment.
        - We only accept blocks that extend the current tip by exactly +1 height.
        - We verify the block_id against the deterministic header hash.
        - We reject or ignore anything that doesn't cleanly extend the local chain.

        NOTE: This is allowed for any node kind (gateway/validator/community),
        since non-validator nodes still need to sync and follow the chain.

        Returns a dict of the shape:
            {
              "ok": bool,
              "status": "appended" | "ignored",
              "error": <str> | None,
            }
        """
        chain = self.ledger.setdefault("chain", [])
        incoming_id = block.get("id")
        incoming_header = block.get("header") or {}

        # Verify hash
        expected = _block_hash(incoming_header)
        if expected != incoming_id:
            return {
                "ok": False,
                "status": "ignored",
                "error": "invalid_block_hash",
            }

        # Decide whether this extends the local tip
        if not chain:
            # First local block: accept if hash matches
            self._apply_block(block)
            self.save_state()
            return {"ok": True, "status": "appended", "error": None}

        tip = chain[-1]
        tip_height = tip["height"]
        new_height = block.get("height", tip_height + 1)
        prev_id = incoming_header.get("prev_id")

        if new_height != tip_height + 1:
            return {
                "ok": False,
                "status": "ignored",
                "error": "height_not_tip_plus_one",
            }
        if prev_id != tip["id"]:
            return {
                "ok": False,
                "status": "ignored",
                "error": "prev_id_mismatch",
            }

        self._apply_block(block)
        self.save_state()
        return {"ok": True, "status": "appended", "error": None}

    # ----------------------- dev mining helper -----------------
    def mine_block(self, payload: Optional[dict] = None) -> Dict[str, Any]:
        """
        DEV helper: mine a single block in a single-node environment.

        Keeps older API calls like `executor.mine_block()` working by:
        - Optionally enqueuing `payload` into the mempool
        - Ensuring the local node_id is a validator
        - Proposing a block
        - Self-voting to reach quorum and finalize

        NOTE: If this node is not configured as a VALIDATOR_NODE, the
        underlying propose_block/vote_block calls will fail with
        `node_not_validator`.
        """
        # Optionally push a tx into the mempool
        if payload:
            try:
                self.add_tx(payload)
            except Exception:
                log.exception("Failed to add_tx(payload) in mine_block, continuing")

        if not self.can_participate_in_consensus():
            raise ValueError("node_not_validator")

        # Ensure local node is recognized as a validator
        if not self.cons.is_validator(self.node_id):
            self.cons.validators.add(self.node_id)

        res = self.propose_block(self.node_id)
        proposal_id = res.get("proposal_id")
        if not proposal_id:
            raise ValueError("proposal_id_missing")
        return self.vote_block(self.node_id, proposal_id)

    # ----------------------- balances helpers ------------------
    def _ensure_balances_dict(self) -> Dict[str, float]:
        """
        Ensure self.ledger has a 'balances' dict and return it.

        Falls back to legacy ledger['accounts'] if 'balances' doesn't
        exist yet, and migrates the data.
        """
        led = getattr(self, "ledger", None)
        if led is None:
            self.ledger = {"balances": {}}
            return self.ledger["balances"]

        balances = led.get("balances")
        if balances is None:
            # migrate from accounts if present
            accounts = self.ledger.get("accounts") or {}
            balances = {aid: acct.get("balance", 0.0) for aid, acct in accounts.items()}
            self.ledger["balances"] = balances
        return balances

    def get_balance(self, account_id: str) -> float:
        balances = self._ensure_balances_dict()
        return float(balances.get(account_id, 0.0))

    def credit(self, account_id: str, amount: float) -> None:
        if amount <= 0:
            return
        balances = self._ensure_balances_dict()
        balances[account_id] = float(balances.get(account_id, 0.0) + float(amount))

    def debit(self, account_id: str, amount: float) -> None:
        if amount <= 0:
            return
        balances = self._ensure_balances_dict()
        current = float(balances.get(account_id, 0.0))
        new_val = current - float(amount)
        if new_val < 0:
            raise ValueError("insufficient_funds")
        balances[account_id] = new_val

    # ----------------------- convenience queries ---------------
    def latest_block(self) -> Optional[dict]:
        chain = self.ledger.get("chain") or []
        return chain[-1] if chain else None

    def latest_block_header(self) -> Optional[dict]:
        block = self.latest_block()
        return block["header"] if block else None

    def consensus_meta(self) -> dict:
        chain = self.ledger.get("chain") or []
        block = chain[-1] if chain else None
        return {
            "ok": True,
            "block": block,
            "validators": sorted(self.cons.validators),
            "quorum_fraction": self.cons.quorum_fraction,
        }

    # ----------------------- GSM / bootstrap helpers -----------
    def _check_gsm_expiry(self, block: dict) -> None:
        """
        Check whether the Genesis Safety Mode (GSM) / bootstrap_mode should
        expire as the network matures.

        This consults genesis params in self.genesis and flips
        self.bootstrap_mode to False when the conditions are met.

        The exact policy can be tuned via genesis_params.json.
        """
        g = getattr(self, "genesis", {}) or {}
        if not g.get("gsm_active"):
            return

        min_height = int(g.get("gsm_min_height") or 0)
        min_validators = int(g.get("gsm_min_validators") or 0)
        height = int(block.get("height", 0))

        if height < min_height:
            return

        active_validators = len(self.cons.validators)
        if active_validators < min_validators:
            return

        # If we reach here, GSM should be disabled
        self.bootstrap_mode = False
        self.genesis["gsm_active"] = False
        self.ledger.setdefault("events", []).append(
            {
                "type": "gsm_expired",
                "height": height,
                "validators": active_validators,
                "ts": _now(),
            }
        )
        self.save_state()
        log.info(
            "Genesis Safety Mode has expired at height=%s with validators=%s",
            height,
            active_validators,
        )


# ------------------------------------------------------------
# Global facade to keep backward-compat imports happy
# ------------------------------------------------------------
class _ExecFacade:
    """
    Thin facade around WeAllExecutor for older code.

    Older modules used to import `executor` directly and call
    executor.add_tx(...), executor.mine_block(...), etc.

    Newer code can explicitly construct / inject a WeAllExecutor, but for the
    integrated node we keep a single global instance and expose it via this
    facade to avoid circular imports.

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
