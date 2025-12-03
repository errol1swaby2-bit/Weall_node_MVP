import os
import json
import hmac
import time
import base64
import hashlib
import secrets
from typing import Dict, Any, Optional

ALGO = "HS256"


def _b64u(x: bytes) -> str:
    return base64.urlsafe_b64encode(x).rstrip(b"=").decode("ascii")


def _b64ud(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: bytes, data: bytes) -> str:
    return _b64u(hmac.new(secret, data, hashlib.sha256).digest())


def _get_env() -> str:
    return os.getenv("WEALL_ENV", "dev").lower()


def _get_secret() -> bytes:
    """
    Return the session secret.

    In dev (WEALL_ENV != "prod"), we allow a weak default so a new node
    can start without extra configuration.

    In prod (WEALL_ENV == "prod"), SESSION_SECRET MUST be set and strong,
    otherwise we raise at runtime so the node fails fast.
    """
    env = _get_env()
    raw = os.getenv("SESSION_SECRET")
    if env in ("prod", "production"):
        if not raw or len(raw) < 32:
            raise RuntimeError(
                "SESSION_SECRET must be set to a strong value (>=32 chars) when WEALL_ENV=prod"
            )
        return raw.encode()
    # Dev / test: fall back to a weak default if unset
    return (raw or "dev-secret").encode()


def issue_token(sub: str, ttl_sec: int = 3600) -> Dict[str, Any]:
    secret = _get_secret()
    now = int(time.time())
    ttl_env = os.getenv("SESSION_TTL")
    ttl = int(ttl_env) if ttl_env is not None else int(ttl_sec)
    exp = now + ttl

    payload: Dict[str, Any] = {
        "sub": str(sub),
        "iat": now,
        "exp": exp,
        "alg": ALGO,
        "nonce": _b64u(secrets.token_bytes(8)),
    }
    header = {"typ": "JWT", "alg": ALGO}

    h = _b64u(json.dumps(header, separators=(",", ":")).encode())
    p = _b64u(json.dumps(payload, separators=(",", ":")).encode())
    sig = _sign(secret, f"{h}.{p}".encode())
    return {"token": f"{h}.{p}.{sig}", "expires": exp}


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        secret = _get_secret()
        h, p, s = token.split(".")
        data = f"{h}.{p}".encode()
        if not hmac.compare_digest(s, _sign(secret, data)):
            return None
        payload = json.loads(_b64ud(p))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
