from __future__ import annotations

"""
Helpers to build and sign protobuf transactions.

Canonical rule:
- Protobuf python modules are imported from weall.v1
"""

from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from weall.v1 import tx_pb2

from .proto_codec import ProtoDomain, compute_tx_id, tx_signing_preimage


def sign_envelope(domain: ProtoDomain, env: tx_pb2.TxEnvelope, sk: Ed25519PrivateKey) -> tx_pb2.TxEnvelope:
    """
    Fill tx_id + signature on the provided envelope.
    """
    env.schema_version = int(domain.schema_version)
    env.chain_id = domain.chain_id

    # tx_id computed with signature cleared
    env.tx_id = compute_tx_id(domain, env)

    pre = tx_signing_preimage(domain, env)
    env.signature = sk.sign(pre)
    return env


def build_treasury_transfer(
    *,
    sender_pubkey: bytes,
    treasury_id: bytes,
    to_pubkey: bytes,
    amount: int,
    memo: str = "",
    group_id: Optional[bytes] = None,
) -> tx_pb2.TxEnvelope:
    """
    Create an unsigned TreasuryTransferTx envelope. Caller signs via sign_envelope().
    """
    env = tx_pb2.TxEnvelope(
        sender=sender_pubkey,
        tx_type=tx_pb2.TX_TREASURY_TRANSFER,
    )

    env.treasury_transfer.treasury_id = treasury_id
    env.treasury_transfer.to = to_pubkey
    env.treasury_transfer.amount = int(amount)
    env.treasury_transfer.memo = memo
    if group_id:
        env.treasury_transfer.group_id = group_id

    return env
