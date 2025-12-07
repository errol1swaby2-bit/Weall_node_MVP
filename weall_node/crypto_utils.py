# weall_node/crypto_utils.py
from __future__ import annotations

"""
Core cryptographic helpers for WeAll.

This module provides:

- Ed25519 helpers (via PyNaCl when available)
- Deterministic KDF helpers for auth and recovery
- AES-GCM messaging helpers using a key derived from the server secret

Notes
-----
* In production you should ensure PyNaCl and cryptography are installed.
* If PyNaCl is not available, Ed25519 helpers will raise at runtime rather than
  silently falling back to an insecure scheme.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
from typing import Any, Dict, Optional, Tuple

# Settings is only used to locate a server-side secret for messaging crypto
try:
    from .settings import Settings as S  # type: ignore
except Exception:  # pragma: no cover - very early boot/import issues
    S = None  # type: ignore

# ---------------------------------------------------------------------------
# Ed25519 via PyNaCl (preferred)
# ---------------------------------------------------------------------------

try:
    from nacl.signing import SigningKey, VerifyKey  # type: ignore
    from nacl.encoding import HexEncoder  # type: ignore
    from nacl.exceptions import BadSignatureError  # type: ignore

    NACL_AVAILABLE = True
except Exception:  # pragma: no cover - fallback when PyNaCl is missing
    SigningKey = None  # type: ignore
    VerifyKey = None  # type: ignore
    HexEncoder = None  # type: ignore
    BadSignatureError = Exception  # type: ignore
    NACL_AVAILABLE = False


def _hex_to_bytes(h: str) -> bytes:
    """Decode hex string to raw bytes, accepting optional 0x prefix."""
    h = h.strip().lower().replace("0x", "")
    return binascii.unhexlify(h.encode("ascii"))


def _bytes_to_hex(b: bytes) -> str:
    """Encode raw bytes to lowercase hex string."""
    return binascii.hexlify(b).decode("ascii")


def ed25519_generate_keypair() -> Tuple[str, str]:
    """
    Generate a new Ed25519 signing keypair.

    Returns
    -------
    (sk_hex, pk_hex) : Tuple[str, str]
        Hex-encoded secret key and public key.
    """
    if not NACL_AVAILABLE:
        raise RuntimeError(
            "PyNaCl is required for Ed25519 key generation. "
            "Install 'pynacl' in your environment."
        )
    sk = SigningKey.generate()
    pk = sk.verify_key
    sk_hex = sk.encode(encoder=HexEncoder).decode("ascii")
    pk_hex = pk.encode(encoder=HexEncoder).decode("ascii")
    return sk_hex, pk_hex


def ed25519_sign(secret_key_hex: str, message: bytes) -> str:
    """
    Sign a message using a hex-encoded Ed25519 secret key.

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
    if not NACL_AVAILABLE:
        raise RuntimeError("PyNaCl is required for Ed25519 signing.")
    # Interpret the hex secret key using HexEncoder
    sk = SigningKey(secret_key_hex, encoder=HexEncoder)
    sig = sk.sign(message).signature
    return _bytes_to_hex(sig)


def ed25519_verify(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    """
    Verify an Ed25519 signature.

    Returns True if the signature is valid, False otherwise.
    """
    if not NACL_AVAILABLE:
        return False
    try:
        vk = VerifyKey(public_key_hex, encoder=HexEncoder)
        sig = _hex_to_bytes(signature_hex)
        vk.verify(message, sig)
        return True
    except BadSignatureError:
        return False
    except Exception:
        return False


# Backwards-compat helper kept for older code paths
def verify_signature_ed25519(
    public_key_hex: str, message: bytes, signature_hex: str
) -> bool:
    return ed25519_verify(public_key_hex, message, signature_hex)


def verify_signature_hmac(secret: str, message: bytes, signature_hex: str) -> bool:
    """
    Legacy HMAC-SHA256 verification helper.

    This is only intended for legacy/dev flows that relied on a shared secret.
    New code should prefer Ed25519.
    """
    try:
        mac = hmac.new(
            secret.encode("utf-8"), msg=message, digestmod=hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(mac, signature_hex.lower())
    except Exception:
        return False


def verify_genesis_signature(message: bytes, signature_hex: str) -> bool:
    """
    Verify a 'genesis' style signature against a configured public key.

    In a full chain this would be used for one-off bootstrapping messages.
    """
    # For now we look for settings on the legacy Settings class. In the future
    # this should be wired to weall_settings.yaml with explicit genesis keys.
    if S is None:
        return False
    pub = getattr(S, "GENESIS_PUBLIC_KEY_HEX", "") or ""
    provider = getattr(S, "CRYPTO_PROVIDER", "pynacl")
    if provider == "pynacl" and pub:
        return verify_signature_ed25519(pub, message, signature_hex)
    if provider == "fallback_hmac":
        secret = getattr(S, "GENESIS_HMAC_SECRET", "") or ""
        if not secret:
            return False
        return verify_signature_hmac(secret, message, signature_hex)
    return False


# ---------------------------------------------------------------------------
# KDF helpers (Argon2id preferred, Scrypt fallback)
# ---------------------------------------------------------------------------

try:
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id  # type: ignore

    ARGON2_AVAILABLE = True
except Exception:  # pragma: no cover
    Argon2id = None  # type: ignore
    ARGON2_AVAILABLE = False

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _argon2id_or_scrypt(
    secret: bytes, *, salt: bytes, length: int = 32
) -> bytes:
    """
    Internal helper: derive a fixed-length key using Argon2id (preferred)
    or Scrypt as a fallback.

    Parameters are tuned for interactive auth / wallet derivation, not high
    volume batch jobs. You can adjust them later via a config layer if needed.
    """
    if ARGON2_AVAILABLE:
        # Values roughly aligned with cryptography docs for Argon2id usage. 0
        # iterations=2, lanes=2, memory_cost=64*1024 KiB (~64 MiB) by default.
        kdf = Argon2id(
            salt=salt,
            length=length,
            iterations=2,
            lanes=2,
            memory_cost=64 * 1024,
            ad=None,
            secret=None,
        )
        return kdf.derive(secret)
    # Scrypt fallback (still memory-hard, but less ideal than Argon2id). 1
    kdf = Scrypt(salt=salt, length=length, n=2 ** 14, r=8, p=1)
    return kdf.derive(secret)


def derive_auth_seed(email: str, password: str, *, salt: bytes) -> bytes:
    """
    Derive a 32-byte auth seed from email + password.

    This does *not* store anything; the caller is responsible for generating
    and persisting `salt` alongside the account metadata. With the same
    email/password/salt triplet, this function returns the same seed.
    """
    material = (email.strip().lower() + "\n" + password).encode("utf-8")
    return _argon2id_or_scrypt(material, salt=salt, length=32)


def derive_recovery_seed(
    answers: Tuple[str, ...],
    *,
    salt: bytes,
    account_pk_hex: str,
) -> bytes:
    """
    Derive a 32-byte recovery seed from security answers + account public key.

    Parameters
    ----------
    answers : Tuple[str, ...]
        Ordered answers to recovery questions. These MUST be supplied in the
        same order during recovery to reproduce the same seed.
    salt : bytes
        Random salt stored alongside the recovery bundle.
    account_pk_hex : str
        Hex-encoded Ed25519 public key for the account this recovery seed
        is bound to.
    """
    normalized = "\n".join(a.strip() for a in answers)
    material = normalized.encode("utf-8") + b"\n" + _hex_to_bytes(account_pk_hex)
    return _argon2id_or_scrypt(material, salt=salt, length=32)


# ---------------------------------------------------------------------------
# Messaging crypto helpers (AES-GCM)
# ---------------------------------------------------------------------------

# Prefer weall_settings (YAML-backed), fallback to legacy Settings.SECRET_KEY
try:
    from weall_settings import settings as _ws  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _ws = None  # type: ignore


def _server_secret() -> str:
    """
    Order of preference:

    1. weall_settings.jwt.secret_key
    2. Settings.SECRET_KEY
    3. literal 'dev' (non-production; do not use in real deployments)
    """
    if (
        _ws is not None
        and getattr(_ws, "jwt", None)
        and getattr(_ws.jwt, "secret_key", None)
    ):
        return str(_ws.jwt.secret_key)
    if S is not None and hasattr(S, "SECRET_KEY") and getattr(S, "SECRET_KEY"):
        return str(S.SECRET_KEY)
    return "dev"  # last resort (non-production)


def _derive_messaging_key() -> bytes:
    """
    Derive a 256-bit AES-GCM key from the server secret using HKDF-SHA256.
    """
    secret = _server_secret().encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"weall-messaging",
    )
    return hkdf.derive(secret)


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def encrypt_message(
    plaintext: str, *, aad: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """
    Encrypt a UTF-8 string with AES-GCM using a key derived from the server secret.

    Returns a JSON-safe dict with base64 fields (nonce, ciphertext, optional aad).
    """
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be a str")
    key = _derive_messaging_key()
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ad: Optional[bytes] = None
    if aad is not None:
        ad = json.dumps(aad, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), ad)
    out: Dict[str, str] = {"nonce": _b64e(nonce), "ciphertext": _b64e(ct)}
    if ad is not None:
        out["aad"] = _b64e(ad)
    return out


def decrypt_message(blob: Dict[str, str]) -> str:
    """
    Decrypt a dict produced by encrypt_message and return the plaintext string.
    """
    if not isinstance(blob, dict):
        raise TypeError("blob must be a dict")
    key = _derive_messaging_key()
    aes = AESGCM(key)
    nonce = _b64d(blob["nonce"])
    ct = _b64d(blob["ciphertext"])
    ad = _b64d(blob["aad"]) if "aad" in blob else None
    pt = aes.decrypt(nonce, ct, ad)
    return pt.decode("utf-8")


# --- End messaging crypto helpers ---
