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
    h = h.strip().lower().replace("0x", "")
    return binascii.unhexlify(h)


def verify_signature_ed25519(
    public_key_hex: str, message: bytes, signature_hex: str
) -> bool:
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
        mac = hmac.new(
            secret.encode("utf-8"), msg=message, digestmod=hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(mac, signature_hex.lower())
    except Exception:
        return False


def verify_genesis_signature(message: bytes, signature_hex: str) -> bool:
    if S.CRYPTO_PROVIDER == "pynacl" and S.GENESIS_PUBLIC_KEY_HEX:
        return verify_signature_ed25519(
            S.GENESIS_PUBLIC_KEY_HEX, message, signature_hex
        )
    if S.CRYPTO_PROVIDER == "fallback_hmac":
        return verify_signature_hmac(S.GENESIS_HMAC_SECRET, message, signature_hex)
    return False


# --- WeAll messaging crypto helpers (AES-GCM) ---
import os, base64, json
from typing import Optional, Dict, Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

# prefer weall_settings (YAML-backed), fallback to legacy Settings
try:
    from weall_settings import settings as _ws  # type: ignore
except Exception:
    _ws = None  # type: ignore

try:
    from .settings import Settings as S  # legacy settings (may not exist)
except Exception:
    S = None  # type: ignore


def _server_secret() -> str:
    """Order of preference: weall_settings.jwt.secret_key -> Settings.SECRET_KEY -> 'dev'."""
    if (
        _ws is not None
        and getattr(_ws, "jwt", None)
        and getattr(_ws.jwt, "secret_key", None)
    ):
        return str(_ws.jwt.secret_key)
    if S is not None and hasattr(S, "SECRET_KEY") and S.SECRET_KEY:
        return str(S.SECRET_KEY)
    return "dev"  # last resort (non-production)


def _derive_key() -> bytes:
    secret = _server_secret().encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"weall-messaging"
    )
    return hkdf.derive(secret)


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def encrypt_message(
    plaintext: str, *, aad: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Encrypt a UTF-8 string with AES-GCM using a key derived from the server secret.
    Returns a JSON-safe dict with base64 fields (nonce, ciphertext, optional aad).
    """
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be a str")
    key = _derive_key()
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ad = None
    if aad is not None:
        ad = json.dumps(aad, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), ad)
    out = {"nonce": _b64e(nonce), "ciphertext": _b64e(ct)}
    if ad is not None:
        out["aad"] = _b64e(ad)
    return out


def decrypt_message(blob: Dict[str, str]) -> str:
    """Decrypt a dict produced by encrypt_message and return the plaintext string."""
    if not isinstance(blob, dict):
        raise TypeError("blob must be a dict")
    key = _derive_key()
    aes = AESGCM(key)
    nonce = _b64d(blob["nonce"])
    ct = _b64d(blob["ciphertext"])
    ad = _b64d(blob["aad"]) if "aad" in blob else None
    pt = aes.decrypt(nonce, ct, ad)
    return pt.decode("utf-8")


# --- End messaging crypto helpers ---
