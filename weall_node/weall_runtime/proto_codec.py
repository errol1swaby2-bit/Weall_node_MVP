# weall_node/weall_runtime/proto_codec.py
from __future__ import annotations

"""
Proto codec helpers.

This module provides:
- base64 encode/decode for TxEnvelope
- canonical bytes for signing/txid derivation
- tx_id derivation (domain-separated)

The executor expects:
    decode_envelope_from_b64(b64: str) -> tx_pb2.TxEnvelope

The verifier in this repo expects:
    compute_tx_id(domain, tx) -> bytes

So we provide compute_tx_id() as a back-compat alias.
"""

import base64
import hashlib
from dataclasses import dataclass

from weall.v1 import tx_pb2


# ------------------------------------------------------------------------------
# Domain separation + hashing
# ------------------------------------------------------------------------------

@dataclass(frozen=True)
class ProtoDomain:
    """
    Domain separation + network binding for tx-id and signatures.
    """
    chain_id: str
    schema_version: int = 1
    domain_tag: bytes = b"WEALL/TX/v1"


def _hash(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def canonical_bytes(tx: tx_pb2.TxEnvelope) -> bytes:
    """
    Canonical bytes for hashing / signing.

    Must exclude signature to avoid circularity.
    Must exclude tx_id because it is derived from canonical content.
    """
    tmp = tx_pb2.TxEnvelope()
    tmp.CopyFrom(tx)
    tmp.signature = b""
    tmp.tx_id = b""
    return tmp.SerializeToString(deterministic=True)


def tx_signing_preimage(domain: ProtoDomain, tx: tx_pb2.TxEnvelope) -> bytes:
    """
    Preimage that is signed by sender:
      SHA256(domain_tag || chain_id || schema_version || canonical_tx_bytes)
    """
    payload = (
        domain.domain_tag
        + domain.chain_id.encode("utf-8")
        + str(int(domain.schema_version)).encode("utf-8")
        + canonical_bytes(tx)
    )
    return _hash(payload)


def derive_tx_id(domain: ProtoDomain, tx: tx_pb2.TxEnvelope) -> bytes:
    """
    tx_id = SHA256(domain separation + canonical tx bytes)
    """
    return tx_signing_preimage(domain, tx)


# Back-compat: some modules import compute_tx_id()
def compute_tx_id(domain: ProtoDomain, tx: tx_pb2.TxEnvelope) -> bytes:
    return derive_tx_id(domain, tx)


# ------------------------------------------------------------------------------
# Base64 helpers (executor-required)
# ------------------------------------------------------------------------------

def to_b64(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def from_b64(s: str) -> bytes:
    return base64.b64decode(s.encode("utf-8"))


def encode_envelope_to_b64(env: tx_pb2.TxEnvelope) -> str:
    """
    Deterministic serialize + base64 encode.
    """
    raw = env.SerializeToString(deterministic=True)
    return to_b64(raw)


def decode_envelope_from_b64(b64: str) -> tx_pb2.TxEnvelope:
    """
    Base64 decode -> parse TxEnvelope.
    """
    raw = from_b64(b64)
    env = tx_pb2.TxEnvelope()
    env.ParseFromString(raw)
    return env
