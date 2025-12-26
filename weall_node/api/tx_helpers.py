from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Optional, Tuple

from weall.v1 import tx_pb2


def sender_bytes_from_user_id(user_id: str) -> bytes:
    """
    Stable, deterministic sender mapping for dev/testing.

    In production this should be derived from the user's public key / address.
    """
    return hashlib.sha256(str(user_id).encode("utf-8")).digest()


def compute_dev_tx_id(env: tx_pb2.TxEnvelope) -> bytes:
    """
    Deterministic tx_id for dev:
    H(tx_type | sender | nonce | payload_bytes)
    """
    b = bytearray()
    b.extend(int(env.tx_type).to_bytes(4, "big", signed=False))
    b.extend(bytes(env.sender))
    b.extend(int(env.nonce).to_bytes(8, "big", signed=False))
    b.extend(env.SerializeToString(deterministic=True))
    return hashlib.sha256(bytes(b)).digest()


def _set_client_time_ms(env: tx_pb2.TxEnvelope, t_ms: int) -> None:
    # client_time_ms field exists in the proto; keep defensive if schema changes
    if hasattr(env, "client_time_ms"):
        try:
            setattr(env, "client_time_ms", int(t_ms))
        except Exception:
            pass


def make_envelope(
    *,
    user_id: str,
    tx_type: int,
    nonce: int,
    fee: int = 0,
    chain_id: str = "",
    schema_version: int = 1,
    client_time_ms: Optional[int] = None,
    fill_payload: Callable[[tx_pb2.TxEnvelope], None],
) -> tx_pb2.TxEnvelope:
    """
    Builds a TxEnvelope and lets caller populate the oneof payload field
    (e.g. env.proposal_create.title = ...).
    """
    env = tx_pb2.TxEnvelope()
    env.chain_id = chain_id
    env.schema_version = int(schema_version)
    env.tx_type = int(tx_type)
    env.sender = sender_bytes_from_user_id(user_id)
    env.nonce = int(nonce)
    env.fee = int(fee)

    now_ms = int(client_time_ms if client_time_ms is not None else int(time.time() * 1000))
    _set_client_time_ms(env, now_ms)

    # Caller sets exactly one payload field (oneof).
    fill_payload(env)

    # Dev mode: empty signature; stable tx_id
    env.signature = b""
    env.tx_id = compute_dev_tx_id(env)
    return env


def next_nonce_for_user(executor: Any, user_id: str) -> int:
    """
    Preferred: use executor.nonce_store if it supports peek_next(sender_hex).
    Fallback: ledger 'dev_nonces'.
    """
    sender_hex = sender_bytes_from_user_id(user_id).hex()

    ns = getattr(executor, "nonce_store", None)
    if ns is not None:
        # Preferred: in-memory NonceStore(expected/require/commit) used by WeAllExecutor
        if hasattr(ns, "expected"):
            try:
                return int(ns.expected(sender_hex))  # type: ignore[attr-defined]
            except Exception:
                pass

        # Alternate: sqlite-backed ProtoNonceStore (peek_next)
        if hasattr(ns, "peek_next"):
            try:
                return int(ns.peek_next(sender_hex))  # type: ignore[attr-defined]
            except Exception:
                pass

    # Legacy fallback (kept for safety, but should not be needed now that NonceStore has commit())
    nonces = executor.ledger.setdefault("dev_nonces", {})
    if not isinstance(nonces, dict):
        executor.ledger["dev_nonces"] = {}
        nonces = executor.ledger["dev_nonces"]
    return int(nonces.get(sender_hex, 0) or 0)


def apply_tx_local_atomic(executor: Any, env: tx_pb2.TxEnvelope) -> Tuple[bool, dict]:
    """
    Applies the TX using proto_apply (nonce-enforced) and persists if supported.
    """
    from weall_node.weall_runtime.proto_apply import apply_proto_tx_atomic

    ok, receipt = apply_proto_tx_atomic(executor.ledger, env, executor.nonce_store)

    # Fallback nonce bump if NonceStore doesn't persist peek_next/commit semantics.
    if ok:
        sender_hex = bytes(env.sender).hex()
        nonces = executor.ledger.setdefault("dev_nonces", {})
        if not isinstance(nonces, dict):
            executor.ledger["dev_nonces"] = {}
            nonces = executor.ledger["dev_nonces"]
        nonces[sender_hex] = int(env.nonce) + 1

        # Persist if supported
        try:
            if hasattr(executor, "save_state"):
                executor.save_state()
        except Exception:
            pass

    return ok, receipt
