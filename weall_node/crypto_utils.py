# weall_node/crypto_utils.py
from __future__ import annotations
import binascii, hmac, hashlib
from .settings import Settings as S

try:
    from nacl.signing import VerifyKey  # type: ignore
    from nacl.encoding import HexEncoder  # type: ignore
    NACL_AVAILABLE = True
except Exception:
    NACL_AVAILABLE = False

def _hex_to_bytes(h: str) -> bytes:
    h = h.strip().lower().replace("0x","")
    return binascii.unhexlify(h)

def verify_signature_ed25519(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    if not NACL_AVAILABLE:
        return False
    try:
        vk = VerifyKey(_hex_to_bytes(public_key_hex), encoder=HexEncoder)
        sig = _hex_to_bytes(signature_hex)
        vk.verify(message, sig)
        return True
    except Exception:
        return False

def verify_signature_hmac(secret: str, message: bytes, signature_hex: str) -> bool:
    try:
        mac = hmac.new(secret.encode("utf-8"), msg=message, digestmod=hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, signature_hex.lower())
    except Exception:
        return False

def verify_genesis_signature(message: bytes, signature_hex: str) -> bool:
    if S.CRYPTO_PROVIDER == "pynacl" and S.GENESIS_PUBLIC_KEY_HEX:
        return verify_signature_ed25519(S.GENESIS_PUBLIC_KEY_HEX, message, signature_hex)
    if S.CRYPTO_PROVIDER == "fallback_hmac":
        return verify_signature_hmac(S.GENESIS_HMAC_SECRET, message, signature_hex)
    return False
