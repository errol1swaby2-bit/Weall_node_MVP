import os
import base64, secrets, hashlib

# DEV-DEFAULT: PBKDF2-SHA256 (pure Python)
# Format: pbkdf2_sha256$iterations$salt_b64$dk_b64

ALGO = os.getenv("PASSWORD_ALGO", "pbkdf2_sha256")
ITER = int(os.getenv("PASSWORD_ITER", "240000"))
SALT_BYTES = int(os.getenv("PASSWORD_SALT_BYTES", "16"))
DKLEN = 32

def _b64(x: bytes) -> str: return base64.b64encode(x).decode("ascii")
def _b64d(s: str) -> bytes: return base64.b64decode(s.encode("ascii"))

def hash_password(password: str) -> str:
    if ALGO != "pbkdf2_sha256":
        raise ValueError(f"Unsupported PASSWORD_ALGO={ALGO} in dev")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER, dklen=DKLEN)
    return f"pbkdf2_sha256${ITER}${_b64(salt)}${_b64(dk)}"

def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    _, it_s, salt_b64, dk_b64 = parts
    it = int(it_s)
    salt = _b64d(salt_b64)
    dk_expected = _b64d(dk_b64)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, it, dklen=len(dk_expected))
    # constant-time compare
    return secrets.compare_digest(dk, dk_expected)
