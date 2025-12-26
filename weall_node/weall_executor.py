from __future__ import annotations

"""
WeAll Executor (final hardening layer)

Adds:
- Block interval loop (auto propose + vote/finalize)
- Proposer rotation (round-robin by chain height)
- Genesis -> k-of-n transition hooks:
    - WEALL_GENESIS_SINGLE_VERIFIER=1: quorum=1 early
    - WEALL_KOFN_START_HEIGHT=N: switch to normal validator set/quorum after N blocks
- Keeps previous:
    - strict prod mode
    - audit proofs (txs_root, receipts_root)
    - crash recovery rebuild
    - compaction

This is still single-process friendly, but the loop structure is “real node shaped”.
"""

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .node_config import NODE_KIND, QUORUM_FRACTION, VALIDATORS
from .weall_runtime import roles as runtime_roles
from .weall_runtime.atomic_store import AtomicStore
from .weall_runtime.audit_proofs import canonical_json_bytes, merkle_root, receipt_hash, sha256_hex
from .weall_runtime.proto_apply import ProtoApplyError, apply_proto_tx_atomic
from .weall_runtime.proto_codec import ProtoDomain, decode_envelope_from_b64
from .weall_runtime.proto_nonce_store import NonceStore
from .weall_runtime.proto_verify import TxVerifyPolicy, TxVerificationError, verify_tx_envelope
from .weall_runtime.state_compact import CompactionPolicy, compact_ledger_in_place

log = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


def _ensure_dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _ensure_list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _bhex(b: bytes) -> str:
    return bytes(b or b"").hex()


def _ledger_state_hash(ledger: Dict[str, Any]) -> str:
    """
    Hash meaningful state (exclude mempool/events).
    """
    stable = dict(ledger)
    stable.pop("mempool", None)
    stable.pop("events", None)
    return sha256_hex(canonical_json_bytes(stable))


# ------------------------------------------------------------------------------
# PBFT-lite consensus driver
# ------------------------------------------------------------------------------


@dataclass
class Finalized:
    proposal_id: str
    proposer: str
    votes: List[str]
    ts: float


class PBFTLite:
    """
    In-process PBFT-ish vote aggregation.
    For now: proposal created locally, votes tracked locally.
    """

    def __init__(self, validators: List[str], quorum_fraction: float = 0.60) -> None:
        self.validators = set(validators)
        self.quorum_fraction = float(quorum_fraction)
        self._lock = threading.Lock()
        self._proposals: Dict[str, dict] = {}
        self._votes: Dict[str, set] = {}
        self._finalized: Dict[str, Finalized] = {}

    def set_validators(self, validators: List[str]) -> None:
        with self._lock:
            self.validators = set(validators)

    def quorum(self, force_one: bool = False) -> int:
        if force_one:
            return 1
        n = max(1, len(self.validators))
        # ceil(n * quorum_fraction)
        return max(1, int((n * self.quorum_fraction) + 0.999999))

    def open_proposal(self, proposer: str, txs: List[dict]) -> str:
        with self._lock:
            proposal_id = sha256_hex(
                f"{proposer}|{_now()}|{len(txs)}|{os.urandom(8).hex()}".encode("utf-8")
            )[:24]
            self._proposals[proposal_id] = {"proposer": proposer, "txs": txs, "ts": _now()}
            self._votes[proposal_id] = set()
            return proposal_id

    def vote(self, voter: str, proposal_id: str, *, force_one: bool = False) -> dict:
        with self._lock:
            if voter not in self.validators and not force_one:
                return {"ok": False, "error": "not_validator"}
            if proposal_id not in self._proposals:
                return {"ok": False, "error": "proposal_missing"}

            self._votes.setdefault(proposal_id, set()).add(voter)

            q = self.quorum(force_one=force_one)
            votes = self._votes.get(proposal_id, set())
            if len(votes) >= q and proposal_id not in self._finalized:
                p = self._proposals[proposal_id]
                self._finalized[proposal_id] = Finalized(
                    proposal_id=proposal_id,
                    proposer=str(p.get("proposer", "")),
                    votes=sorted(list(votes)),
                    ts=_now(),
                )

            return {"ok": True, "proposal_id": proposal_id, "votes": sorted(list(votes)), "quorum": q}

    def finalized(self, proposal_id: str) -> Optional[Finalized]:
        with self._lock:
            return self._finalized.get(proposal_id)


# ------------------------------------------------------------------------------
# Executor
# ------------------------------------------------------------------------------


class WeAllExecutor:
    def __init__(
        self,
        data_dir: str,
        node_id: str,
        node_kind: Optional[runtime_roles.NodeKind] = None,
        *,
        chain_id: Optional[str] = None,
        schema_version: Optional[int] = None,
        dev_allow_unsigned: Optional[bool] = None,
        strict_prod: Optional[bool] = None,
    ) -> None:
        self.data_dir = str(data_dir)
        self.node_id = str(node_id)
        self.node_kind = node_kind or NODE_KIND

        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

        self.chain_id = str(chain_id or os.environ.get("WEALL_CHAIN_ID", "weall-dev"))
        self.schema_version = int(schema_version or int(os.environ.get("WEALL_SCHEMA_VERSION", "1")))

        self.strict_prod = bool(
            strict_prod
            if strict_prod is not None
            else (os.environ.get("WEALL_STRICT_PROD", "0").strip() == "1")
        )

        default_dev_allow = (os.environ.get("WEALL_DEV_ALLOW_UNSIGNED", "1").strip() == "1")
        self.dev_allow_unsigned = bool(dev_allow_unsigned if dev_allow_unsigned is not None else default_dev_allow)
        if self.strict_prod:
            self.dev_allow_unsigned = False

        # Genesis -> k-of-n transition hooks
        self.genesis_single_verifier = os.environ.get("WEALL_GENESIS_SINGLE_VERIFIER", "1").strip() == "1"
        self.kofn_start_height = int(os.environ.get("WEALL_KOFN_START_HEIGHT", "50") or 50)

        self.domain = ProtoDomain(chain_id=self.chain_id, schema_version=self.schema_version)

        self.store = AtomicStore(Path(self.data_dir) / "ledger_state.json", keep_backups=3)
        self.ledger: Dict[str, Any] = _ensure_dict(self.store.load() or {})

        self._lock = threading.RLock()

        self.cons = PBFTLite(validators=self._active_validators_for_height(0), quorum_fraction=float(QUORUM_FRACTION))
        self.nonce_store = NonceStore(self.ledger.setdefault("nonces", {}))

        self.wecoin = None

        self._loop_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_tick = 0.0

        self._migrate_ledger()
        self._startup_recovery()
        self._startup_compaction_if_enabled()

        # Start loop automatically unless disabled
        if os.environ.get("WEALL_AUTO_LOOP", "1").strip() == "1":
            self.start_loop()

    # ----------------------- topology ------------------

    def can_participate_in_consensus(self) -> bool:
        return self.node_kind == runtime_roles.NodeKind.VALIDATOR_NODE

    # ----------------------- validator set + proposer rotation ------------------

    def _all_validators(self) -> List[str]:
        vals = list(VALIDATORS) if VALIDATORS else [self.node_id]
        # deterministic order
        vals = sorted({str(v) for v in vals if str(v).strip()})
        if not vals:
            vals = [self.node_id]
        return vals

    def _active_validators_for_height(self, height: int) -> List[str]:
        """
        Genesis mode: optionally run with a single verifier early, then expand to full set.
        """
        height = int(height or 0)
        if self.genesis_single_verifier and height < self.kofn_start_height:
            return [self.node_id]
        return self._all_validators()

    def _force_one_quorum_for_height(self, height: int) -> bool:
        """
        Force quorum=1 during early genesis if enabled.
        """
        height = int(height or 0)
        return bool(self.genesis_single_verifier and height < self.kofn_start_height)

    def proposer_for_next_height(self) -> str:
        """
        Round-robin proposer selection by *next* height.
        """
        h = self.chain_height()
        vals = self._active_validators_for_height(h)
        idx = h % max(1, len(vals))
        return vals[idx]

    def _refresh_consensus_membership(self) -> None:
        """
        Keep PBFT-lite validator set aligned with the current phase.
        """
        h = self.chain_height()
        self.cons.set_validators(self._active_validators_for_height(h))

    # ----------------------- ledger schema ------------------

    def _migrate_ledger(self) -> None:
        led = self.ledger
        v = int(led.get("schema_version", 1) or 1)

        if v < 5:
            led.setdefault("chain", [])
            led.setdefault("events", [])
            led.setdefault("mempool", {"order": [], "by_id": {}})
            led.setdefault("pending_blocks", {})

            led.setdefault("tx_index", {})
            led.setdefault("tx_receipts", {})
            led.setdefault("tx_receipt_hashes", {})
            led.setdefault("block_receipts", {})

            led.setdefault("balances", {})
            led.setdefault("accounts", {})
            led.setdefault("nonces", {})

            led.setdefault("chain_id", self.chain_id)
            led.setdefault("proto_schema_version", self.schema_version)

            led.setdefault("state_hash", "")
            led["schema_version"] = 5

        led["chain"] = _ensure_list(led.get("chain"))
        led["events"] = _ensure_list(led.get("events"))
        led["pending_blocks"] = _ensure_dict(led.get("pending_blocks"))
        led["tx_index"] = _ensure_dict(led.get("tx_index"))
        led["tx_receipts"] = _ensure_dict(led.get("tx_receipts"))
        led["tx_receipt_hashes"] = _ensure_dict(led.get("tx_receipt_hashes"))
        led["block_receipts"] = _ensure_dict(led.get("block_receipts"))
        led["balances"] = _ensure_dict(led.get("balances"))
        led["accounts"] = _ensure_dict(led.get("accounts"))
        led["nonces"] = _ensure_dict(led.get("nonces"))

        mp = led.get("mempool")
        if not isinstance(mp, dict):
            mp = {"order": [], "by_id": {}}
            led["mempool"] = mp
        mp["order"] = _ensure_list(mp.get("order"))
        mp["by_id"] = _ensure_dict(mp.get("by_id"))

        led["chain_id"] = str(led.get("chain_id") or self.chain_id)
        led["proto_schema_version"] = int(led.get("proto_schema_version") or self.schema_version)

    def _validate_ledger_for_save(self) -> Dict[str, Any]:
        led = _ensure_dict(self.ledger)

        # strict pinning
        if self.strict_prod:
            if str(led.get("chain_id") or "") != self.chain_id:
                raise ValueError("ledger chain_id mismatch in strict prod")
            if int(led.get("proto_schema_version") or 0) != int(self.schema_version):
                raise ValueError("ledger proto_schema_version mismatch in strict prod")

        for k in ["pending_blocks", "tx_index", "tx_receipts", "tx_receipt_hashes", "block_receipts", "balances", "accounts", "nonces"]:
            if not isinstance(led.get(k), dict):
                led[k] = {}
        for k in ["chain", "events"]:
            if not isinstance(led.get(k), list):
                led[k] = []
        mp = led.get("mempool")
        if not isinstance(mp, dict):
            led["mempool"] = {"order": [], "by_id": {}}
            mp = led["mempool"]
        if not isinstance(mp.get("order"), list):
            mp["order"] = []
        if not isinstance(mp.get("by_id"), dict):
            mp["by_id"] = {}

        led["chain_id"] = str(led.get("chain_id") or self.chain_id)
        led["proto_schema_version"] = int(led.get("proto_schema_version") or self.schema_version)
        led["schema_version"] = int(led.get("schema_version") or 5)

        led["state_hash"] = _ledger_state_hash(led)
        return led

    def save_state(self) -> None:
        with self._lock:
            safe = self._validate_ledger_for_save()
            self.store.save(safe)

    def _event(self, typ: str, data: dict) -> None:
        self.ledger.setdefault("events", []).append({"ts": _now(), "type": typ, "data": data})

    # ----------------------- recovery ------------------

    def _startup_recovery(self) -> None:
        with self._lock:
            stored_hash = str(self.ledger.get("state_hash") or "")
            if not self.ledger.get("chain"):
                self.ledger["state_hash"] = _ledger_state_hash(self.ledger)
                return

            rebuilt = self._rebuild_from_chain()
            rebuilt_hash = _ledger_state_hash(rebuilt)

            if stored_hash and stored_hash == rebuilt_hash:
                return

            self._event("recovery_rebuild", {"stored_hash": stored_hash, "rebuilt_hash": rebuilt_hash})
            self.ledger = rebuilt
            self.nonce_store = NonceStore(self.ledger.setdefault("nonces", {}))
            self.save_state()

    def _rebuild_from_chain(self) -> Dict[str, Any]:
        src_chain = _ensure_list(self.ledger.get("chain"))
        fresh: Dict[str, Any] = {
            "schema_version": 5,
            "chain_id": self.chain_id,
            "proto_schema_version": self.schema_version,
            "chain": [],
            "events": [],
            "mempool": {"order": [], "by_id": {}},
            "pending_blocks": {},
            "tx_index": {},
            "tx_receipts": {},
            "tx_receipt_hashes": {},
            "block_receipts": {},
            "balances": {},
            "accounts": {},
            "nonces": {},
        }
        nonce_store = NonceStore(fresh.setdefault("nonces", {}))

        for height, blk in enumerate(src_chain):
            if not isinstance(blk, dict):
                continue

            txs = blk.get("txs", [])
            if not isinstance(txs, list):
                txs = []

            receipts_for_block: List[dict] = []
            tx_ids: List[str] = []
            receipt_hashes: List[str] = []

            for pos, item in enumerate(txs):
                if not isinstance(item, dict):
                    continue
                b64 = str(item.get("b64") or "")
                tx_id_hex = str(item.get("tx_id") or "")
                if not b64:
                    receipts_for_block.append({"ok": False, "error": "missing_b64", "pos": pos, "tx_id": tx_id_hex})
                    continue

                try:
                    env = decode_envelope_from_b64(b64)
                except Exception:
                    receipts_for_block.append({"ok": False, "error": "bad_b64_or_proto", "pos": pos, "tx_id": tx_id_hex})
                    continue

                try:
                    ok, r = apply_proto_tx_atomic(fresh, env, nonce_store)
                    rid = _bhex(getattr(env, "tx_id", b"") or b"") or tx_id_hex
                    receipts_for_block.append({"ok": bool(ok), "receipt": r, "pos": pos, "tx_id": rid})

                    if rid:
                        fresh["tx_receipts"][rid] = r
                        rh = receipt_hash(r)
                        fresh["tx_receipt_hashes"][rid] = rh
                        tx_ids.append(rid)
                        receipt_hashes.append(rh)

                        fresh["tx_index"][rid] = {
                            "height": int(height),
                            "block_id": str(blk.get("block_id") or ""),
                            "pos": int(pos),
                            "proposal_id": str(blk.get("proposal_id") or ""),
                        }
                except Exception as e:
                    receipts_for_block.append({"ok": False, "error": f"apply_error:{type(e).__name__}", "pos": pos, "tx_id": tx_id_hex})

            txs_root = merkle_root(tx_ids)
            receipts_root = merkle_root(receipt_hashes)

            fresh_block = dict(blk)
            fresh_block["height"] = int(height)
            fresh_block.setdefault("header", {})
            if not isinstance(fresh_block["header"], dict):
                fresh_block["header"] = {}
            fresh_block["header"].update({"height": int(height), "txs_root": txs_root, "receipts_root": receipts_root})

            fresh["chain"].append(fresh_block)
            key = str(blk.get("proposal_id") or blk.get("block_id") or f"h{height}")
            fresh["block_receipts"][key] = {
                "applied": sum(1 for x in receipts_for_block if x.get("ok")),
                "receipts": receipts_for_block,
                "ts": float(blk.get("ts") or _now()),
                "block_id": str(blk.get("block_id") or ""),
                "height": int(height),
                "txs_root": txs_root,
                "receipts_root": receipts_root,
            }

        fresh["state_hash"] = _ledger_state_hash(fresh)
        return fresh

    # ----------------------- compaction ------------------

    def _startup_compaction_if_enabled(self) -> None:
        if os.environ.get("WEALL_COMPACT_ON_START", "0").strip() != "1":
            return
        self.compact_state(reason="startup")

    def compact_state(self, reason: str = "manual") -> dict:
        with self._lock:
            pol = CompactionPolicy(
                keep_recent_blocks=int(os.environ.get("WEALL_KEEP_RECENT_BLOCKS", "200")),
                keep_events=int(os.environ.get("WEALL_KEEP_EVENTS", "2000")),
                prune_tx_receipts=os.environ.get("WEALL_PRUNE_TX_RECEIPTS", "1").strip() == "1",
                keep_receipts_for_blocks=int(os.environ.get("WEALL_KEEP_RECEIPTS_FOR_BLOCKS", "200")),
                drop_mempool=os.environ.get("WEALL_DROP_MEMPOOL_ON_COMPACT", "0").strip() == "1",
            )
            stats = compact_ledger_in_place(self.ledger, policy=pol)
            stats["reason"] = reason
            self._event("compact", stats)
            self.save_state()
            return stats

    # ----------------------- chain helpers ------------------

    def chain_height(self) -> int:
        return len(_ensure_list(self.ledger.get("chain")))

    def latest_block(self) -> Optional[dict]:
        chain = _ensure_list(self.ledger.get("chain"))
        return chain[-1] if chain else None

    def _prev_block_id(self) -> str:
        b = self.latest_block()
        return str(b.get("block_id") or "genesis") if isinstance(b, dict) else "genesis"

    def _deterministic_block_id(self, *, prev_block_id: str, proposer: str, proposal_id: str, tx_ids: List[str]) -> str:
        raw = ("|".join([prev_block_id, proposer, proposal_id] + list(tx_ids))).encode("utf-8")
        return sha256_hex(raw)[:32]

    # ----------------------- verification ------------------

    def _verify_envelope_policy(self, env) -> Tuple[bool, str]:
        try:
            policy = TxVerifyPolicy(require_signature=(not self.dev_allow_unsigned))
            verify_tx_envelope(self.domain, env, policy=policy)
            return True, ""
        except TxVerificationError as e:
            if self.dev_allow_unsigned and not self.strict_prod:
                return True, ""
            return False, str(e)
        except Exception as e:
            if self.dev_allow_unsigned and not self.strict_prod:
                return True, ""
            return False, f"verify_error:{type(e).__name__}"

    # ----------------------- mempool ------------------

    def submit_proto_envelope_b64(self, b64: str) -> dict:
        with self._lock:
            try:
                env = decode_envelope_from_b64(b64)
            except Exception:
                return {"ok": False, "error": "bad_b64_or_proto"}

            ok, err = self._verify_envelope_policy(env)
            if self.strict_prod and not ok:
                return {"ok": False, "error": err or "verify_failed"}

            tx_id_hex = _bhex(getattr(env, "tx_id", b"") or b"") or hashlib.sha256(b64.encode("utf-8")).hexdigest()[:48]

            mp = self.ledger.setdefault("mempool", {"order": [], "by_id": {}})
            if not isinstance(mp, dict):
                self.ledger["mempool"] = {"order": [], "by_id": {}}
                mp = self.ledger["mempool"]

            mp["order"] = _ensure_list(mp.get("order"))
            mp["by_id"] = _ensure_dict(mp.get("by_id"))

            if tx_id_hex in mp["by_id"]:
                return {"ok": True, "deduped": True, "tx_id": tx_id_hex}

            mp["by_id"][tx_id_hex] = b64
            mp["order"].append(tx_id_hex)

            self.save_state()
            return {"ok": True, "tx_id": tx_id_hex}

    def pop_mempool(self, limit: int = 100) -> List[dict]:
        with self._lock:
            mp = _ensure_dict(self.ledger.get("mempool"))
            order = _ensure_list(mp.get("order"))
            by_id = _ensure_dict(mp.get("by_id"))

            n = max(0, int(limit))
            take = order[:n]
            mp["order"] = order[len(take):]

            out: List[dict] = []
            for tx_id_hex in take:
                b64 = by_id.pop(str(tx_id_hex), None)
                if b64:
                    out.append({"tx_id": str(tx_id_hex), "b64": str(b64)})

            self.ledger["mempool"] = mp
            return out

    def mempool_size(self) -> int:
        mp = _ensure_dict(self.ledger.get("mempool"))
        order = _ensure_list(mp.get("order"))
        return len(order)

    # ----------------------- propose/finalize ------------------

    def propose_block(self, proposer: Optional[str] = None, limit: int = 100) -> dict:
        with self._lock:
            self._refresh_consensus_membership()
            proposer = proposer or self.node_id
            txs = self.pop_mempool(limit=limit)

            proposal_id = self.cons.open_proposal(proposer=proposer, txs=txs)
            self.ledger.setdefault("pending_blocks", {})[proposal_id] = {
                "proposal_id": proposal_id,
                "proposer": proposer,
                "txs": txs,
                "ts": _now(),
                "prev_block_id": self._prev_block_id(),
            }
            self.save_state()
            return {"ok": True, "proposal_id": proposal_id, "count": len(txs)}

    def vote_finalize(self, proposal_id: str, voter: Optional[str] = None) -> dict:
        with self._lock:
            self._refresh_consensus_membership()

            voter = voter or self.node_id
            force_one = self._force_one_quorum_for_height(self.chain_height())

            res = self.cons.vote(voter=voter, proposal_id=proposal_id, force_one=force_one)
            if not res.get("ok"):
                return res

            fin = self.cons.finalized(proposal_id)
            if not fin:
                return {"ok": True, "proposal_id": proposal_id, "finalized": False, **res}

            pending = _ensure_dict(self.ledger.get("pending_blocks")).get(proposal_id)
            if not pending:
                # already applied?
                if proposal_id in _ensure_dict(self.ledger.get("block_receipts")):
                    return {"ok": True, "proposal_id": proposal_id, "finalized": True, "already_applied": True, **res}
                return {"ok": False, "error": "pending_block_missing"}

            applied, receipts, tx_ids, receipt_hashes = self._apply_pending_block(pending)

            prev_block_id = str(pending.get("prev_block_id") or self._prev_block_id())
            block_id = self._deterministic_block_id(
                prev_block_id=prev_block_id,
                proposer=str(pending.get("proposer") or ""),
                proposal_id=str(proposal_id),
                tx_ids=tx_ids,
            )

            txs_root = merkle_root(tx_ids)
            receipts_root = merkle_root(receipt_hashes)

            height = self.chain_height()
            block = {
                "block_id": block_id,
                "proposal_id": proposal_id,
                "proposer": pending.get("proposer"),
                "votes": fin.votes,
                "txs": pending.get("txs", []),
                "ts": fin.ts,
                "height": height,
                "prev_block_id": prev_block_id,
                "header": {
                    "height": height,
                    "prev_id": prev_block_id,
                    "ts": fin.ts,
                    "txs_root": txs_root,
                    "receipts_root": receipts_root,
                },
            }

            self.ledger.setdefault("chain", []).append(block)
            self.ledger.setdefault("block_receipts", {})[proposal_id] = {
                "applied": applied,
                "receipts": receipts,
                "finalized": fin.votes,
                "ts": fin.ts,
                "block_id": block_id,
                "height": int(height),
                "txs_root": txs_root,
                "receipts_root": receipts_root,
            }

            self._index_block_txs(block)

            # cleanup pending
            try:
                del self.ledger["pending_blocks"][proposal_id]
            except Exception:
                pass

            # compaction cadence
            every_n = int(os.environ.get("WEALL_COMPACT_EVERY_N_BLOCKS", "0") or 0)
            if every_n > 0 and (self.chain_height() % every_n) == 0:
                self.compact_state(reason=f"every_{every_n}_blocks")

            self.save_state()
            return {"ok": True, "proposal_id": proposal_id, "finalized": True, "applied": applied, "block_id": block_id, **res}

    def _apply_pending_block(self, pb: dict) -> Tuple[int, List[dict], List[str], List[str]]:
        txs = pb.get("txs") or []
        applied = 0
        receipts: List[dict] = []
        tx_ids: List[str] = []
        receipt_hashes: List[str] = []

        for i, item in enumerate(txs):
            b64 = str(item.get("b64", "")) if isinstance(item, dict) else ""
            hinted_tx_id = str(item.get("tx_id", "")) if isinstance(item, dict) else ""

            if not b64:
                receipts.append({"ok": False, "error": "missing_b64", "pos": i, "tx_id": hinted_tx_id})
                continue

            try:
                env = decode_envelope_from_b64(b64)
            except Exception:
                receipts.append({"ok": False, "error": "bad_b64_or_proto", "pos": i, "tx_id": hinted_tx_id})
                continue

            okv, err = self._verify_envelope_policy(env)
            if self.strict_prod and not okv:
                receipts.append({"ok": False, "error": f"verify_failed:{err}", "pos": i, "tx_id": hinted_tx_id})
                continue

            try:
                ok, r = apply_proto_tx_atomic(self.ledger, env, self.nonce_store)

                rid = _bhex(getattr(env, "tx_id", b"") or b"") or hinted_tx_id
                receipts.append({"ok": bool(ok), "receipt": r, "pos": i, "tx_id": rid})

                if rid:
                    self.ledger.setdefault("tx_receipts", {})[rid] = r
                    rh = receipt_hash(r)
                    self.ledger.setdefault("tx_receipt_hashes", {})[rid] = rh
                    tx_ids.append(rid)
                    receipt_hashes.append(rh)

                if ok:
                    applied += 1
            except ProtoApplyError as e:
                receipts.append({"ok": False, "error": str(e), "pos": i, "tx_id": hinted_tx_id})
            except Exception as e:
                receipts.append({"ok": False, "error": f"apply_error:{type(e).__name__}", "pos": i, "tx_id": hinted_tx_id})

        return applied, receipts, tx_ids, receipt_hashes

    def _index_block_txs(self, block: dict) -> None:
        tx_index = self.ledger.setdefault("tx_index", {})
        if not isinstance(tx_index, dict):
            self.ledger["tx_index"] = {}
            tx_index = self.ledger["tx_index"]

        height = int(block.get("height", 0) or 0)
        block_id = str(block.get("block_id") or "")
        proposal_id = str(block.get("proposal_id") or "")

        txs = block.get("txs", [])
        if not isinstance(txs, list):
            return

        for pos, item in enumerate(txs):
            if not isinstance(item, dict):
                continue
            tx_id = str(item.get("tx_id") or "").strip()
            if not tx_id:
                continue
            tx_index[tx_id] = {"height": height, "block_id": block_id, "pos": int(pos), "proposal_id": proposal_id}

    # ----------------------- status ------------------

    def status(self) -> dict:
        return {
            "ok": True,
            "height": self.chain_height(),
            "epoch": 0,
            "bootstrap_mode": bool(self.ledger.get("bootstrap_mode", False)),
            "driver": {
                "ok": True,
                "running": bool(self._loop_thread and self._loop_thread.is_alive()),
                "topic": "weall-consensus",
                "block_interval_sec": int(os.environ.get("WEALL_BLOCK_INTERVAL_SECONDS", "10")),
                "node_id": self.node_id,
                "is_validator_node": self.can_participate_in_consensus(),
                "validators": self._active_validators_for_height(self.chain_height()),
                "chain_height": self.chain_height(),
                "chain_id": self.chain_id,
                "schema_version": self.schema_version,
                "strict_prod": self.strict_prod,
                "dev_allow_unsigned": self.dev_allow_unsigned,
                "genesis_single_verifier": self.genesis_single_verifier,
                "kofn_start_height": self.kofn_start_height,
                "next_proposer": self.proposer_for_next_height(),
                "mempool_size": self.mempool_size(),
            },
        }

    # ----------------------- block interval loop ------------------

    def start_loop(self) -> None:
        with self._lock:
            if self._loop_thread and self._loop_thread.is_alive():
                return
            self._stop_event.clear()
            t = threading.Thread(target=self._loop_main, name="weall-consensus-loop", daemon=True)
            self._loop_thread = t
            t.start()

    def stop_loop(self) -> None:
        self._stop_event.set()
        t = self._loop_thread
        if t and t.is_alive():
            try:
                t.join(timeout=2.0)
            except Exception:
                pass

    def _loop_main(self) -> None:
        interval = float(os.environ.get("WEALL_BLOCK_INTERVAL_SECONDS", "10") or 10.0)
        tick_sleep = max(0.2, min(2.0, interval / 10.0))

        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("consensus loop tick failed")

            time.sleep(tick_sleep)

    def tick(self) -> None:
        """
        One loop iteration:
        - refresh validator set based on phase
        - if it's our turn to propose and mempool has txs, propose
        - as a validator, auto-vote and finalize pending proposals we know about
        """
        with self._lock:
            self._refresh_consensus_membership()

            interval = float(os.environ.get("WEALL_BLOCK_INTERVAL_SECONDS", "10") or 10.0)
            now = _now()
            if (now - self._last_tick) < (interval * 0.50):
                # avoid over-ticking
                pass
            self._last_tick = now

            # Auto-propose only if validator node
            if self.can_participate_in_consensus():
                next_proposer = self.proposer_for_next_height()
                if self.node_id == next_proposer and self.mempool_size() > 0:
                    self.propose_block(proposer=self.node_id, limit=int(os.environ.get("WEALL_BLOCK_MAX_TX", "200") or 200))

            # Auto-vote/finalize known pending blocks
            if self.can_participate_in_consensus():
                pbs = _ensure_dict(self.ledger.get("pending_blocks"))
                # vote in deterministic order
                for pid in sorted(pbs.keys()):
                    try:
                        self.vote_finalize(pid, voter=self.node_id)
                    except Exception:
                        log.exception("vote_finalize failed for %s", pid)

            # Update state hash regularly (and persist if configured)
            if os.environ.get("WEALL_SAVE_EVERY_TICK", "0").strip() == "1":
                self.save_state()


# ------------------------------------------------------------------------------
# Singleton executor
# ------------------------------------------------------------------------------

DATA_DIR = os.environ.get("WEALL_DATA_DIR", str(Path(os.getcwd()) / "data"))
NODE_ID = os.environ.get("WEALL_NODE_ID", "local-node")
CHAIN_ID = os.environ.get("WEALL_CHAIN_ID", "weall-dev")
SCHEMA_VERSION = int(os.environ.get("WEALL_SCHEMA_VERSION", "1"))
STRICT_PROD = os.environ.get("WEALL_STRICT_PROD", "0").strip() == "1"
DEV_ALLOW_UNSIGNED = os.environ.get("WEALL_DEV_ALLOW_UNSIGNED", "1").strip() == "1"

executor = WeAllExecutor(
    DATA_DIR,
    node_id=NODE_ID,
    node_kind=NODE_KIND,
    chain_id=CHAIN_ID,
    schema_version=SCHEMA_VERSION,
    dev_allow_unsigned=DEV_ALLOW_UNSIGNED,
    strict_prod=STRICT_PROD,
)
