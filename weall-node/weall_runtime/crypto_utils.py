# weall_runtime/crypto_utils.py
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

def verify_ed25519_sig(pub_b64: str, message: bytes, sig_b64: str) -> bool:
    """
    Verify Ed25519 signature. pub_b64 and sig_b64 are base64 strings.
    """
    try:
        pub = base64.b64decode(pub_b64)
        sig = base64.b64decode(sig_b64)
        pk = ed25519.Ed25519PublicKey.from_public_bytes(pub)
        pk.verify(sig, message)
        return True
    except Exception:
        return False
