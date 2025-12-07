# weall_node/settings.py
from __future__ import annotations

import os
from pathlib import Path
from typing import List


def _env(name: str, default: str) -> str:
    """Read an environment variable with a string fallback."""
    v = os.getenv(name)
    return v if v is not None else default


def _env_bool(name: str, default: str = "0") -> bool:
    """Boolean env helper accepting 1/0, true/false, yes/no."""
    raw = os.getenv(name, default).strip().lower()
    return raw in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_list(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """
    Legacy env-backed settings for WeAll Node.

    This class is used as a *fallback* in a few places:
      - weall_node.api.p2p_overlay  → ROOT_DIR, P2P_BOOTSTRAP
      - weall_node.crypto_utils     → SECRET_KEY (for server-side messaging crypto)
      - weall_node.weall_api        → older email / server defaults (if accessed)

    The more complete, spec-aligned configuration lives in `weall_settings.py`
    (YAML + Pydantic). This module is intentionally lightweight and safe to
    import anywhere.
    """

    # ---------- Paths ----------
    ROOT_DIR: str = _env(
        "WEALL_ROOT_DIR",
        str(Path(__file__).resolve().parent.parent),
    )
    DATA_DIR: str = _env(
        "WEALL_DATA_DIR",
        str(Path(ROOT_DIR) / "data"),
    )

    # ---------- Security / Secrets ----------
    # Single shared secret used as a last-resort for:
    #  - crypto_utils._server_secret() (AES-GCM messaging)
    # In production you should set WEALL_SECRET_KEY to a strong random value.
    SECRET_KEY: str = _env("WEALL_SECRET_KEY", "dev")

    # Optional distinct JWT secret (if used by legacy flows)
    JWT_SECRET_KEY: str = _env("WEALL_JWT_SECRET_KEY", SECRET_KEY)

    # ---------- Server ----------
    SERVER_HOST: str = _env("WEALL_HOST", "0.0.0.0")
    SERVER_PORT: int = _env_int("WEALL_PORT", 8000)

    # CORS origins (comma-separated). Default to "*" for legacy dev builds.
    CORS_ORIGINS: List[str] = _env_list("WEALL_CORS_ORIGINS", "*")

    # ---------- IPFS ----------
    IPFS_API_URL: str = _env("WEALL_IPFS_API_URL", "http://127.0.0.1:5001")
    IPFS_GATEWAY_URL: str = _env("WEALL_IPFS_GATEWAY_URL", "https://ipfs.io/ipfs/")

    # ---------- Content limits ----------
    # Max upload size in bytes (25 MB by default)
    MAX_UPLOAD_SIZE: int = _env_int("WEALL_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)

    # ---------- Autosave ----------
    AUTOSAVE_ENABLED: bool = _env_bool("WEALL_AUTOSAVE", "1")
    AUTOSAVE_INTERVAL_SEC: int = _env_int("WEALL_AUTOSAVE_INTERVAL_SEC", 300)

    # ---------- PoH / Governance (safety thresholds) ----------
    # Minimum juror votes required to finalize a PoH application or dispute.
    POH_MIN_VOTES: int = _env_int("WEALL_POH_MIN_VOTES", 7)

    # Number of epochs a juror must wait before being eligible again,
    # to reduce capture / over-selection.
    JUROR_COOLDOWN_EPOCHS: int = _env_int("WEALL_JUROR_COOLDOWN_EPOCHS", 3)

    # Stage thresholds (MVP: 3 stages, roughly corresponding to tiers).
    # These can be used by governance / juror selection logic to decide
    # quorum slices or confidence bands.
    STAGE1_MIN: int = _env_int("WEALL_STAGE1_MIN", 0)
    STAGE1_MAX: int = _env_int("WEALL_STAGE1_MAX", 10)
    STAGE1_PCT: float = _env_float("WEALL_STAGE1_PCT", 0.25)

    STAGE2_MIN: int = _env_int("WEALL_STAGE2_MIN", 11)
    STAGE2_MAX: int = _env_int("WEALL_STAGE2_MAX", 50)
    STAGE2_PCT: float = _env_float("WEALL_STAGE2_PCT", 0.25)

    STAGE3_MIN: int = _env_int("WEALL_STAGE3_MIN", 51)
    STAGE3_MAX: int = _env_int("WEALL_STAGE3_MAX", 100)
    STAGE3_PCT: float = _env_float("WEALL_STAGE3_PCT", 0.50)

    # Quorum model identifier (for future use by consensus/governance)
    # e.g. "bft_2f1" → classic 2f+1 over 3f+1 validators
    QUORUM_MODEL: str = _env("WEALL_QUORUM_MODEL", "bft_2f1")

    # ---------- Epoch / Rewards (WeCoin) ----------
    # Epoch / block interval in seconds (spec default: 600s = 10 minutes)
    EPOCH_DURATION_SEC: int = _env_int("WEALL_EPOCH_DURATION_SEC", 600)

    # Base block reward (WeCoin units) before halvings are applied.
    # The detailed halving schedule lives in the runtime ledger; this
    # value is for bootstrap / defaults only.
    BLOCK_REWARD: int = _env_int("WEALL_BLOCK_REWARD", 100)

    # Reward pool split (5-way, even by default):
    #   - Validator
    #   - Juror
    #   - Storage / operator
    #   - Creator
    #   - Treasury
    POOL_SPLIT_VALIDATOR: float = 0.20
    POOL_SPLIT_JUROR: float = 0.20
    POOL_SPLIT_STORAGE: float = 0.20
    POOL_SPLIT_CREATOR: float = 0.20
    POOL_SPLIT_TREASURY: float = 0.20

    # ---------- P2P / Overlay ----------
    # Comma-separated list of bootstrap URLs, used by api/p2p_overlay.py
    # Example:
    #   WEALL_P2P_BOOTSTRAP="https://node1.example.com,https://node2.example.com"
    P2P_BOOTSTRAP: str = _env("WEALL_P2P_BOOTSTRAP", "")

    # ---------- Email (legacy flows only) ----------
    # These remain unused by most of the new stack, but are kept here
    # for compatibility with older experimental auth email flows.
    SMTP_HOST: str = _env("SMTP_HOST", "")
    SMTP_PORT: int = _env_int("SMTP_PORT", 587)
    SMTP_USER: str = _env("SMTP_USER", "")
    SMTP_PASS: str = _env("SMTP_PASS", "")
    SMTP_FROM: str = _env("SMTP_FROM", "")
    SMTP_TLS: bool = _env_bool("SMTP_TLS", "1")
