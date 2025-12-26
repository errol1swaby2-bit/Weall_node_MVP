from __future__ import annotations

"""
Protobuf TX verification helpers.

Verifies:
- schema_version + chain_id
- sender pubkey length
- tx_id matches canonical hash (domain separated)
- signature verifies over canonical signing preimage

Note:
In WeAll dev mode you may choose to accept unsigned envelopes (policy.require_signature=False).
"""

from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from weall.v1 import tx_pb2

from .proto_codec import ProtoDomain, compute_tx_id, tx_signing_preimage


@dataclass(frozen=True)
class TxVerifyPolicy:
    require_signature: bool = True
    sender_key_len: int = 32  # Ed25519 public key length
    sig_len: int = 64         # Ed25519 signature length


class TxVerificationError(ValueError):
    pass


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise TxVerificationError(msg)


def verify_tx_envelope(
    domain: ProtoDomain,
    tx: tx_pb2.TxEnvelope,
    *,
    policy: Optional[TxVerifyPolicy] = None,
) -> None:
    pol = policy or TxVerifyPolicy()

    _require(int(tx.schema_version) == int(domain.schema_version), "schema_version mismatch")
    _require(tx.chain_id == domain.chain_id, "chain_id mismatch")

    sender = bytes(tx.sender)
    _require(len(sender) == pol.sender_key_len, f"sender must be {pol.sender_key_len} bytes (ed25519 pubkey)")

    _require(bool(tx.tx_id), "tx_id missing")
    expected_id = compute_tx_id(domain, tx)
    _require(bytes(tx.tx_id) == expected_id, "tx_id mismatch")

    sig = bytes(tx.signature)
    if pol.require_signature:
        _require(len(sig) == pol.sig_len, f"signature must be {pol.sig_len} bytes (ed25519 signature)")
    else:
        # allow unsigned if policy says so
        if not sig:
            return

    preimage = tx_signing_preimage(domain, tx)
    try:
        pk = Ed25519PublicKey.from_public_bytes(sender)
        pk.verify(sig, preimage)
    except Exception as e:
        raise TxVerificationError(f"signature verification failed: {e}") from e
