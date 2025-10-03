"""
weall_runtime.crypto_symmetric

Fernet-like symmetric encryption using AES-256-CBC + PKCS7 padding.
Pure Python via pycryptodome, Termux-safe replacement for cryptography.fernet.
"""

import base64
import os
import hashlib
from Crypto.Cipher import AES


class SimpleFernet:
    """
    Minimal Fernet-like symmetric encryption class.
    Uses AES-256-CBC with PKCS7 padding.
    """

    def __init__(self, key: bytes):
        # Ensure a 32-byte key using SHA-256
        self.key = hashlib.sha256(key).digest()

    def encrypt(self, data: bytes) -> bytes:
        iv = os.urandom(16)
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        pad_len = 16 - (len(data) % 16)
        data += bytes([pad_len]) * pad_len
        ct = cipher.encrypt(data)
        return base64.urlsafe_b64encode(iv + ct)

    def decrypt(self, token: bytes) -> bytes:
        raw = base64.urlsafe_b64decode(token)
        iv, ct = raw[:16], raw[16:]
        cipher = AES.new(self.key, AES.MODE_CBC, iv)
        pt = cipher.decrypt(ct)
        pad_len = pt[-1]
        return pt[:-pad_len]
