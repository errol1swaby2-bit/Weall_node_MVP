# weall_node/weall_runtime/crypto_utils.py
"""
Minimal crypto utilities without heavy OS build deps.

Security note:
- For MVP/testing, we avoid native libs. We emulate ed25519-like
  interfaces but use HMAC-SHA256 for signatures.
- Public key == private key (32 random bytes). This is NOT secure,
  but keeps tests/dev frictionless on Termux/Android.
- Replace with a real ed25519 (e.g., pynacl) in production.

API:
- generate_keypair() -> (priv: bytes, pub: bytes)
- sign_message(priv: bytes, message: bytes) -> sig: bytes
- verify_ed25519_sig(pub: bytes, message: bytes, signature: bytes) -> bool
"""

import os
import hmac
import hashlib
from typing import Tuple


def generate_keypair() -> Tuple[bytes, bytes]:
    priv = os.urandom(32)
    # insecure placeholder: public mirrors private for HMAC verification
    pub = priv
    return priv, pub


def sign_message(priv: bytes, message: bytes) -> bytes:
    return hmac.new(priv, message, hashlib.sha256).digest()


def verify_ed25519_sig(pub: bytes, message: bytes, signature: bytes) -> bool:
    # Because pub == priv in this MVP, verification uses pub as HMAC key
    expected = hmac.new(pub, message, hashlib.sha256).digest()
    return hmac.compare_digest(expected, signature)
