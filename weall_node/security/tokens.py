# Pure-stdlib signed tokens: header.payload.signature (base64url)
import os, json, hmac, time, base64, hashlib, secrets
ALGO = "HS256"
def _b64u(x: bytes) -> str: return base64.urlsafe_b64encode(x).rstrip(b"=").decode("ascii")
def _b64ud(s: str) -> bytes: return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
def _sign(secret: bytes, data: bytes) -> str:
    return _b64u(hmac.new(secret, data, hashlib.sha256).digest())
def issue_token(sub: str, ttl_sec: int = 3600) -> dict:
    secret = os.getenv("SESSION_SECRET", "dev-secret").encode()
    now = int(time.time()); exp = now + int(os.getenv("SESSION_TTL", str(ttl_sec)))
    payload = {"sub": str(sub), "iat": now, "exp": exp, "alg": ALGO, "nonce": _b64u(secrets.token_bytes(8))}
    header = {"typ":"JWT","alg":ALGO}
    h = _b64u(json.dumps(header, separators=(",",":")).encode())
    p = _b64u(json.dumps(payload, separators=(",",":")).encode())
    sig = _sign(secret, f"{h}.{p}".encode())
    return {"token": f"{h}.{p}.{sig}", "expires": exp}
def verify_token(token: str) -> dict | None:
    try:
        secret = os.getenv("SESSION_SECRET", "dev-secret").encode()
        h, p, s = token.split("."); data = f"{h}.{p}".encode()
        if not hmac.compare_digest(s, _sign(secret, data)): return None
        payload = json.loads(_b64ud(p))
        if int(payload.get("exp", 0)) < int(time.time()): return None
        return payload
    except Exception:
        return None
