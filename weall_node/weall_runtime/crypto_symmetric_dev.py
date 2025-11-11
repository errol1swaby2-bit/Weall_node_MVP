import os, hmac, hashlib, base64, secrets, time

# DEV-ONLY symmetric "cipher": XOR with a SHA256-based keystream + HMAC for integrity.
# This is NOT secure crypto. It's purely to unblock local dev when Crypto/AES isn't available.
# Activate by importing from this module, or via __init__ fallback below.

def _kdf(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()

def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    ctr = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + nonce + ctr.to_bytes(4, "big")).digest())
        ctr += 1
    return bytes(out[:length])

class SimpleFernet:
    def __init__(self, secret: str):
        self.key = _kdf(secret)

    def encrypt(self, data: bytes) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        nonce = secrets.token_bytes(12)
        ks = _keystream(self.key, nonce, len(data))
        ct = bytes(a ^ b for a, b in zip(data, ks))
        mac = hmac.new(self.key, nonce + ct, hashlib.sha256).digest()
        token = b"dev1|" + nonce + ct + mac
        return base64.urlsafe_b64encode(token).decode("ascii")

    def decrypt(self, token: str) -> bytes:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        if not raw.startswith(b"dev1|"):
            raise ValueError("Bad token")
        raw = raw[5:]
        nonce, rest = raw[:12], raw[12:]
        ct, mac = rest[:-32], rest[-32:]
        if not hmac.compare_digest(mac, hmac.new(self.key, nonce + ct, hashlib.sha256).digest()):
            raise ValueError("Bad MAC")
        ks = _keystream(self.key, nonce, len(ct))
        pt = bytes(a ^ b for a, b in zip(ct, ks))
        return pt
