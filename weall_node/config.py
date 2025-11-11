# weall_node/config.py
import os
import yaml
from typing import Any, Dict, List

# -------- Defaults (non-secret) --------
_DEFAULT: Dict[str, Any] = {
    "persistence": {"driver": "json", "sqlite_path": "weall.db"},
    "ipfs": {
        "require_ipfs": False,
        "api_url": "http://127.0.0.1:5001",
        "gateway": "https://ipfs.io",
    },
    "governance": {"tier3_quorum_fraction": 0.6, "tier3_yes_fraction": 0.5},
    "chain": {"block_max_txs": 1000},
    "security": {
        "require_signed_votes": True,
        "require_signed_tx": False,
        # Non-secret security knobs (secrets via ENV below)
        "session_cookie_name": "weall_session",
        "jwt_expire_min": 60,  # can be overridden by env JWT_EXPIRE_MIN
    },
    "logging": {"level": "INFO", "json": True},
    "runtime": {
        "editable_roots": ["weall_node", "frontend", "pallets", "runtime"],
        "backup_dir": ".weall_backups",
    },
    # NEW: Server & CORS control what HTTP address the app binds to and what the frontend should call
    "server": {
        "host": "0.0.0.0",  # uvicorn bind address
        "port": 8000,  # uvicorn port
        "public_base_url": "http://127.0.0.1:8000",  # what clients should use to reach this backend
    },
    "cors": {
        # Origins allowed to call with credentials (cookies)
        "origins": [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    },
}

# -------- ENV secrets / overrides (do NOT bake secrets in YAML) --------
# You can set these in your shell or .env: SECRET_KEY, JWT_EXPIRE_MIN, SESSION_COOKIE_NAME
_ENV_MAP = {
    ("security", "jwt_expire_min"): ("JWT_EXPIRE_MIN", int),
    ("security", "session_cookie_name"): ("SESSION_COOKIE_NAME", str),
    # Secret is not stored in YAML; only via ENV
    ("security", "secret_key"): ("SECRET_KEY", str),
}


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_env_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    # Apply typed ENV overrides
    for (section, key), (env_name, cast) in _ENV_MAP.items():
        val = os.getenv(env_name)
        if val is not None:
            try:
                casted = cast(val)
            except Exception:
                casted = val
            cfg.setdefault(section, {})
            cfg[section][key] = casted
    return cfg


def load_config(repo_root: str) -> Dict[str, Any]:
    """
    Loads the YAML config from repo_root/weall_config.yaml.
    Returns defaults if the file doesn't exist or can't be parsed.
    Also applies ENV overrides for certain keys & secrets.
    """
    path = os.path.join(repo_root, "weall_config.yaml")
    cfg = dict(_DEFAULT)

    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            cfg = _deep_merge(cfg, data)
        except Exception:
            # fall back to defaults
            pass

    cfg = _apply_env_overrides(cfg)

    # Ensure derived types / minimal normalization
    # Normalize CORS origins to a list
    origins = cfg.get("cors", {}).get("origins")
    if isinstance(origins, str):
        cfg["cors"]["origins"] = [origins]

    return cfg


# -------- Small helpers used by the app --------
def get_public_base_url(cfg: Dict[str, Any]) -> str:
    """
    The URL clients should use when calling this backend. Example:
    http://127.0.0.1:8000  or  https://api.weall.org
    """
    return cfg.get("server", {}).get("public_base_url") or "http://127.0.0.1:8000"


def get_bind_host(cfg: Dict[str, Any]) -> str:
    return str(cfg.get("server", {}).get("host", "0.0.0.0"))


def get_bind_port(cfg: Dict[str, Any]) -> int:
    return int(cfg.get("server", {}).get("port", 8000))


def get_cors_origins(cfg: Dict[str, Any]) -> List[str]:
    return list(cfg.get("cors", {}).get("origins", []))


def get_session_cookie_name(cfg: Dict[str, Any]) -> str:
    return cfg.get("security", {}).get("session_cookie_name", "weall_session")


def get_jwt_expire_min(cfg: Dict[str, Any]) -> int:
    return int(cfg.get("security", {}).get("jwt_expire_min", 60))


def get_secret_key() -> str:
    """
    SECRET_KEY is intentionally not read from YAML.
    Provide it via environment (SECRET_KEY). A weak dev fallback is used only if missing.
    """
    return os.getenv("SECRET_KEY", "dev-only-change-me")
