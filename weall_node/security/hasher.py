# weall_node/security/hasher.py
from __future__ import annotations

"""
Password hashing utilities for WeAll.

IMPORTANT
---------
This module is ONLY responsible for hashing and verifying authentication
passwords for login. It is *not* used for deriving account or recovery keys.
Those are handled by `weall_node.crypto_utils` (Argon2id/Scrypt KDFs).

Supported hash formats (prefix-based):

- "argon2id$..."  : Argon2id with parameters encoded in the string.
- "pbkdf2$..."    : PBKDF2-HMAC-SHA256, iteration count + salt + hash in hex.
- "sha256$..."    : legacy direct SHA256(password+salt) hex (verify-only, no new hashes).

New passwords should always be hashed using Argon2id when available,
falling back to PBKDF2 when Argon2 is not installed.
"""

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Argon2id support (preferred)
# ---------------------------------------------------------------------------

try:
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id  # type: ignore

    ARGON2_AVAILABLE = True
except Exception:  # pragma: no cover - env without Argon2id
    Argon2id = None  # type: ignore
    ARGON2_AVAILABLE = False

# PBKDF2-HMAC-SHA256 from stdlib
from hashlib import pbkdf2_hmac


@dataclass
class Argon2Params:
    iterations: int = 2
    memory_cost_kib: int = 64 * 1024  # ~64 MiB
    parallelism: int = 2
    hash_len: int = 32


DEFAULT_ARGON2_PARAMS = Argon2Params()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _split_prefix(stored: str) -> Tuple[str, str]:
    """
    Split "prefix$rest" into ("prefix", "rest").
    If no '$' is present, treat as legacy and return ("", stored).
    """
    if "$" not in stored:
        return "", stored
    prefix, rest = stored.split("$", 1)
    return prefix, rest


# ---------------------------------------------------------------------------
# Argon2id-based password hashing
# ---------------------------------------------------------------------------


def _argon2_hash(password: str, params: Argon2Params) -> str:
    if not ARGON2_AVAILABLE:
        raise RuntimeError("Argon2id is not available in this environment.")

    salt = os.urandom(16)
    pwd_bytes = password.encode("utf-8")

    kdf = Argon2id(
        salt=salt,
        length=params.hash_len,
        iterations=params.iterations,
        lanes=params.parallelism,
        memory_cost=params.memory_cost_kib,
        ad=None,
        secret=None,
    )
    digest = kdf.derive(pwd_bytes)

    # Encode parameters + salt + hash in a compact, readable way.
    # Format:
    #   argon2id$iters:mem:lanes:len$salt_b64$hash_b64
    meta = f"{params.iterations}:{params.memory_cost_kib}:{params.parallelism}:{params.hash_len}"
    return f"argon2id${meta}${_b64e(salt)}${_b64e(digest)}"


def _argon2_verify(password: str, stored_rest: str) -> bool:
    if not ARGON2_AVAILABLE:
        # Can't verify Argon2 hashes if library is missing
        return False

    try:
        meta, salt_b64, digest_b64 = stored_rest.split("$", 2)
        iters_str, mem_str, lanes_str, len_str = meta.split(":")
        params = Argon2Params(
            iterations=int(iters_str),
            memory_cost_kib=int(mem_str),
            parallelism=int(lanes_str),
            hash_len=int(len_str),
        )

        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
        pwd_bytes = password.encode("utf-8")

        kdf = Argon2id(
            salt=salt,
            length=params.hash_len,
            iterations=params.iterations,
            lanes=params.parallelism,
            memory_cost=params.memory_cost_kib,
            ad=None,
            secret=None,
        )
        candidate = kdf.derive(pwd_bytes)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PBKDF2-HMAC-SHA256 password hashing (fallback)
# ---------------------------------------------------------------------------


def _pbkdf2_hash(password: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    pwd_bytes = password.encode("utf-8")
    dk = pbkdf2_hmac("sha256", pwd_bytes, salt, iterations, dklen=32)
    # Format:
    #   pbkdf2$iters$salt_hex$hash_hex
    return f"pbkdf2${iterations}${salt.hex()}${dk.hex()}"


def _pbkdf2_verify(password: str, stored_rest: str) -> bool:
    try:
        iter_str, salt_hex, hash_hex = stored_rest.split("$", 2)
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        pwd_bytes = password.encode("utf-8")
        candidate = pbkdf2_hmac("sha256", pwd_bytes, salt, iterations, dklen=len(expected))
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Legacy SHA256-based hashing (verify-only)
# ---------------------------------------------------------------------------


def _legacy_sha256_verify(password: str, stored_rest: str) -> bool:
    """
    Legacy format: "sha256$salt_hex$hash_hex" where hash = SHA256(salt || password).

    This is supported for verification ONLY. New hashes must not be created
    in this format.
    """
    try:
        salt_hex, hash_hex = stored_rest.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        pwd_bytes = password.encode("utf-8")
        candidate = hashlib.sha256(salt + pwd_bytes).digest()
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """
    Hash a password for storage.

    Uses Argon2id when available; otherwise PBKDF2-HMAC-SHA256.

    Returns
    -------
    stored : str
        A self-describing, prefix-based hash string, e.g.:

        - "argon2id$iters:mem:lanes:len$salt_b64$hash_b64"
        - "pbkdf2$iters$salt_hex$hash_hex"
    """
    if not isinstance(password, str):
        raise TypeError("password must be a string")

    if ARGON2_AVAILABLE:
        return _argon2_hash(password, DEFAULT_ARGON2_PARAMS)
    # Fallback for environments without Argon2id
    return _pbkdf2_hash(password)


def verify_password(password: str, stored: str) -> bool:
    """
    Verify a password against a stored hash.

    Supports multiple schemes via the prefix before the first "$".
    """
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if not stored:
        return False

    prefix, rest = _split_prefix(stored)

    if prefix == "argon2id":
        return _argon2_verify(password, rest)
    if prefix == "pbkdf2":
        return _pbkdf2_verify(password, rest)
    if prefix == "sha256":
        # legacy, verify-only
        return _legacy_sha256_verify(password, rest)

    # If there was no prefix, treat as legacy sha256 to avoid locking out users
    # who signed up before prefixes were introduced.
    if prefix == "":
        return _legacy_sha256_verify(password, stored)

    # Unknown prefix
    return False


# Backwards-compat aliases (if older code used different names)
def hash_secret(secret: str) -> str:
    """
    Backwards-compatible alias for hash_password.
    """
    return hash_password(secret)


def verify_secret(secret: str, stored: str) -> bool:
    """
    Backwards-compatible alias for verify_password.
    """
    return verify_password(secret, stored)
