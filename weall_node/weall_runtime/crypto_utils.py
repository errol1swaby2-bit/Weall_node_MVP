# weall_node/weall_runtime/crypto_utils.py
from __future__ import annotations

"""
Runtime crypto facade for WeAll.

This module exists as a thin, backwards-compatible wrapper around the
core cryptographic helpers in `weall_node.crypto_utils`.

Historically this file implemented a fake "Ed25519" using HMAC-SHA256
with public == private. That was acceptable only for local MVP demos.

Now, all public functions in this module delegate to the real, production
primitives:

- Ed25519 for signing / verification
- Argon2id/Scrypt-based KDFs for auth & recovery seeds
- AES-GCM for server-side messaging encryption

Anything still importing from `weall_node.weall_runtime.crypto_utils`
will transparently gain the upgraded security model.
"""

from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .. import crypto_utils as core_crypto


# ---------------------------------------------------------------------------
# Ed25519 keypairs and signatures
# ---------------------------------------------------------------------------


def generate_keypair() -> Tuple[str, str]:
    """
    Generate a new Ed25519 keypair.

    Returns
    -------
    (sk_hex, pk_hex) : Tuple[str, str]
        Hex-encoded secret and public keys.

    This replaces the old "public == private" HMAC-based scheme.
    """
    return core_crypto.ed25519_generate_keypair()


def sign_message(secret_key_hex: str, message: bytes) -> str:
    """
    Sign an arbitrary message with the given Ed25519 secret key.

    Parameters
    ----------
    secret_key_hex : str
        Hex-encoded Ed25519 secret key (32 bytes).
    message : bytes
        Message to sign.

    Returns
    -------
    signature_hex : str
        Hex-encoded signature.
    """
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("message must be bytes")
    return core_crypto.ed25519_sign(secret_key_hex, bytes(message))


def verify_signature_ed25519(
    public_key_hex: str,
    message: bytes,
    signature_hex: str,
) -> bool:
    """
    Verify an Ed25519 signature.

    This is the canonical verification function. It is kept under the
    old name so existing callers (e.g. ledger/governance) don't break.
    """
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("message must be bytes")
    return core_crypto.ed25519_verify(public_key_hex, bytes(message), signature_hex)


# Some older code paths may refer to verify_ed25519_sig; keep an alias.
def verify_ed25519_sig(
    public_key_hex: str,
    message: bytes,
    signature_hex: str,
) -> bool:
    """
    Backwards-compatible alias for verify_signature_ed25519.
    """
    return verify_signature_ed25519(public_key_hex, message, signature_hex)


# ---------------------------------------------------------------------------
# KDF helpers for auth + recovery
# ---------------------------------------------------------------------------


def derive_auth_seed(email: str, password: str, *, salt: bytes) -> bytes:
    """
    Derive a 32-byte auth seed from email + password + salt.

    This is used as the root material for account keys (auth/sign/encrypt)
    and replaces any earlier ad-hoc KDF usage in runtime code.
    """
    return core_crypto.derive_auth_seed(email=email, password=password, salt=salt)


def derive_recovery_seed(
    answers: Sequence[str],
    *,
    salt: bytes,
    account_pk_hex: str,
) -> bytes:
    """
    Derive a 32-byte recovery seed from security answers and the account public key.

    Parameters
    ----------
    answers : Sequence[str]
        Ordered answers to recovery questions.
    salt : bytes
        Salt stored alongside the recovery metadata.
    account_pk_hex : str
        Hex-encoded Ed25519 public key this recovery seed is bound to.
    """
    # Ensure we pass a tuple to the core helper (for stable ordering semantics)
    answers_tuple = tuple(str(a) for a in answers)
    return core_crypto.derive_recovery_seed(
        answers_tuple,
        salt=salt,
        account_pk_hex=account_pk_hex,
    )


# ---------------------------------------------------------------------------
# Messaging encryption (AES-GCM) passthrough
# ---------------------------------------------------------------------------


def encrypt_message(
    plaintext: str,
    *,
    aad: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Encrypt a UTF-8 string with AES-GCM using a key derived from the server secret.

    This is a direct passthrough to `crypto_utils.encrypt_message` and is
    intended for short-lived server<->client control messages, not for
    large media payloads.
    """
    return core_crypto.encrypt_message(plaintext, aad=aad)


def decrypt_message(blob: Dict[str, str]) -> str:
    """
    Decrypt a dict produced by `encrypt_message` and return the plaintext string.
    """
    return core_crypto.decrypt_message(blob)


# ---------------------------------------------------------------------------
# Genesis / special signatures
# ---------------------------------------------------------------------------


def verify_genesis_signature(message: bytes, signature_hex: str) -> bool:
    """
    Verify a 'genesis' signature against the configured public key.

    This simply defers to `crypto_utils.verify_genesis_signature`. It is
    used in bootstrapping/initialization flows where a pre-baked key may
    attest to configuration or initial state.
    """
    if not isinstance(message, (bytes, bytearray)):
        raise TypeError("message must be bytes")
    return core_crypto.verify_genesis_signature(bytes(message), signature_hex)


# ---------------------------------------------------------------------------
# Legacy compatibility shims (no-op / pass-through)
# ---------------------------------------------------------------------------


def is_dev_insecure_mode() -> bool:
    """
    Return True if the core crypto module is using obviously insecure settings.

    Currently this always returns False because the old 'HMAC pretending to be
    Ed25519' path has been removed. It exists only so older callers that
    conditionally warned on dev-mode continue to import cleanly.
    """
    return False
