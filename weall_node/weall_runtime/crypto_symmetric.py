# weall_node/weall_runtime/crypto_symmetric.py
from __future__ import annotations

"""
Symmetric cryptography utilities for WeAll (runtime layer).

This module provides a small, opinionated wrapper around AES-GCM for cases
where the caller already has (or derives) a symmetric key.

Use cases
---------
- Encrypting small metadata blobs before storing them off-node.
- Protecting short-lived tokens / state that should NOT use the global
  server messaging key (for that, see `weall_node.crypto_utils.encrypt_message`).

This module is *not* for password hashing or account key derivation.
Those live in:

- weall_node.security.hasher       (password hashing)
- weall_node.crypto_utils          (KDFs for auth/recovery, Ed25519, messaging)

API overview
------------
- generate_key()           -> bytes
- encrypt_bytes(key, pt)   -> token: bytes
- decrypt_bytes(key, tok)  -> pt: bytes
- encrypt_json(key, obj)   -> token: str (URL-safe base64)
- decrypt_json(key, tok)   -> obj: dict

Backwards-compat aliases:
- encrypt_blob(...)  -> encrypt_bytes(...)
- decrypt_blob(...)  -> decrypt_bytes(...)
"""

import base64
import json
import os
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_key(length: int = 32) -> bytes:
    """
    Generate a random symmetric key.

    Parameters
    ----------
    length : int
        Key length in bytes. AES-GCM supports 16, 24, or 32 bytes. Default is
        32 bytes (AES-256).

    Returns
    -------
    key : bytes
        Random key material.
    """
    if length not in (16, 24, 32):
        raise ValueError("AES-GCM key length must be 16, 24, or 32 bytes")
    return os.urandom(length)


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


# ---------------------------------------------------------------------------
# Core AES-GCM helpers
# ---------------------------------------------------------------------------


def encrypt_bytes(
    key: bytes,
    plaintext: bytes,
    *,
    aad: Optional[bytes] = None,
) -> bytes:
    """
    Encrypt raw bytes with AES-GCM.

    Parameters
    ----------
    key : bytes
        Symmetric AES key (16/24/32 bytes).
    plaintext : bytes
        Data to encrypt.
    aad : Optional[bytes]
        Optional "additional authenticated data" that is bound to the
        ciphertext but not encrypted.

    Returns
    -------
    token : bytes
        A compact binary blob: nonce || ciphertext+tag

    Notes
    -----
    - Nonce is 12 random bytes.
    - Ciphertext includes the GCM authentication tag.
    """
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("key must be bytes")
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext must be bytes")

    aes = AESGCM(bytes(key))
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, bytes(plaintext), aad)
    return nonce + ct


def decrypt_bytes(
    key: bytes,
    token: bytes,
    *,
    aad: Optional[bytes] = None,
) -> bytes:
    """
    Decrypt a blob produced by encrypt_bytes.

    Parameters
    ----------
    key : bytes
        Symmetric AES key (16/24/32 bytes).
    token : bytes
        Blob produced by encrypt_bytes (nonce || ciphertext+tag).
    aad : Optional[bytes]
        The same additional authenticated data used during encryption.

    Returns
    -------
    plaintext : bytes

    Raises
    ------
    cryptography.exceptions.InvalidTag
        If authentication fails (wrong key, tampered data, mismatched AAD).
    """
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("key must be bytes")
    if not isinstance(token, (bytes, bytearray)):
        raise TypeError("token must be bytes")
    if len(token) < 12:
        raise ValueError("token is too short to contain nonce + ciphertext")

    aes = AESGCM(bytes(key))
    nonce = bytes(token[:12])
    ct = bytes(token[12:])
    return aes.decrypt(nonce, ct, aad)


# ---------------------------------------------------------------------------
# JSON convenience wrappers
# ---------------------------------------------------------------------------


def encrypt_json(
    key: bytes,
    obj: Dict[str, Any],
    *,
    aad: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Encrypt a JSON-serializable dict using AES-GCM.

    Parameters
    ----------
    key : bytes
        Symmetric AES key (16/24/32 bytes).
    obj : dict
        JSON-serializable dictionary to encrypt.
    aad : Optional[dict]
        Optional JSON-serializable AAD that will be authenticated but not
        encrypted.

    Returns
    -------
    token : str
        URL-safe base64 string.
    """
    if not isinstance(obj, dict):
        raise TypeError("obj must be a dict")

    pt = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    aad_bytes: Optional[bytes] = None
    if aad is not None:
        aad_bytes = json.dumps(aad, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )

    blob = encrypt_bytes(key, pt, aad=aad_bytes)
    return _b64e(blob)


def decrypt_json(
    key: bytes,
    token: str,
    *,
    aad: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Decrypt a token produced by encrypt_json back into a dict.

    Parameters
    ----------
    key : bytes
        Symmetric AES key (16/24/32 bytes).
    token : str
        URL-safe base64 token from encrypt_json.
    aad : Optional[dict]
        Optional JSON-serializable AAD (must match the one used for encryption).

    Returns
    -------
    obj : dict
    """
    if not isinstance(token, str):
        raise TypeError("token must be a str")

    blob = _b64d(token)
    aad_bytes: Optional[bytes] = None
    if aad is not None:
        aad_bytes = json.dumps(aad, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )

    pt = decrypt_bytes(key, blob, aad=aad_bytes)
    return json.loads(pt.decode("utf-8"))


# ---------------------------------------------------------------------------
# Backwards-compat aliases
# ---------------------------------------------------------------------------


def encrypt_blob(
    key: bytes,
    data: bytes,
    *,
    aad: Optional[bytes] = None,
) -> bytes:
    """
    Backwards-compatible alias for encrypt_bytes. Kept for older code that
    may still import encrypt_blob/decrypt_blob.
    """
    return encrypt_bytes(key, data, aad=aad)


def decrypt_blob(
    key: bytes,
    blob: bytes,
    *,
    aad: Optional[bytes] = None,
) -> bytes:
    """
    Backwards-compatible alias for decrypt_bytes.
    """
    return decrypt_bytes(key, blob, aad=aad)
