# weall_node/settings.py
from __future__ import annotations
import os
from typing import List


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None else default


class Settings:
    # ---------- Paths ----------
    ROOT_DIR: str = _env(
        "WEALL_ROOT_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    )
    DATA_DIR: str = _env("WEALL_DATA_DIR", os.path.join(ROOT_DIR, "data"))
    UPLOAD_DIR: str = _env("WEALL_UPLOAD_DIR", os.path.join(DATA_DIR, "uploads"))
    STATE_FILE: str = _env(
        "WEALL_STATE_FILE", os.path.join(DATA_DIR, "executor_state.json")
    )
    CONTENT_INDEX_FILE: str = _env(
        "WEALL_CONTENT_INDEX_FILE", os.path.join(DATA_DIR, "content_index.json")
    )
    USERS_FILE: str = _env("WEALL_USERS_FILE", os.path.join(DATA_DIR, "users.json"))

    # ---------- Networking / IPFS ----------
    IPFS_API_ADDR: str = _env("WEALL_IPFS_ADDR", "/ip4/127.0.0.1/tcp/5001/http")
    API_HOST: str = _env("WEALL_API_HOST", "0.0.0.0")
    API_PORT: int = int(_env("WEALL_API_PORT", "8000"))

    # ---------- Security / CORS ----------
    CORS_ORIGINS: List[str] = [
        o.strip()
        for o in _env(
            "WEALL_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://10.0.2.2:5173",
        ).split(",")
        if o.strip()
    ]
    CORS_ALLOW_CREDENTIALS: bool = True

    # ---------- Content limits ----------
    MAX_UPLOAD_SIZE: int = int(
        _env("WEALL_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
    )  # 25MB

    # ---------- Autosave ----------
    AUTOSAVE_ENABLED: bool = _env("WEALL_AUTOSAVE", "1") not in ("0", "false", "False")
    AUTOSAVE_INTERVAL_SEC: int = int(_env("WEALL_AUTOSAVE_INTERVAL_SEC", "300"))

    # ---------- PoH / Governance ----------
    POH_MIN_VOTES: int = int(_env("WEALL_POH_MIN_VOTES", "7"))
    JUROR_COOLDOWN_EPOCHS: int = int(_env("WEALL_JUROR_COOLDOWN_EPOCHS", "3"))

    # Governance thresholds (MVP)
    GOV_MIN_VOTERS_PCT: float = float(
        _env("WEALL_GOV_MIN_VOTERS_PCT", "0.10")
    )  # 10% of eligible voters
    GOV_PASS_PCT: float = float(
        _env("WEALL_GOV_PASS_PCT", "0.50")
    )  # simple majority of participating votes
    GOV_ELIGIBLE_TIER: int = int(
        _env("WEALL_GOV_ELIGIBLE_TIER", "2")
    )  # Tier-2+ can vote

    # ---------- Metrics ----------
    METRICS_ENABLED: bool = _env("WEALL_METRICS", "1") not in ("0", "false", "False")

    # ---------- Crypto provider ----------
    CRYPTO_PROVIDER: str = _env(
        "WEALL_CRYPTO_PROVIDER", "pynacl"
    )  # "pynacl" | "fallback_hmac"

    # ---------- Genesis / Bootstrapping ----------
    BOOTSTRAP_MODE: bool = _env("WEALL_BOOTSTRAP_MODE", "1") not in (
        "0",
        "false",
        "False",
    )
    GENESIS_ADMIN_ENABLED: bool = _env("WEALL_GENESIS_ADMIN_ENABLED", "1") not in (
        "0",
        "false",
        "False",
    )
    GENESIS_PUBLIC_KEY_HEX: str = _env("WEALL_GENESIS_PUBLIC_KEY_HEX", "")
    GENESIS_HMAC_SECRET: str = _env("WEALL_GENESIS_HMAC_SECRET", "dev-genesis-secret")

    BOOTSTRAP_MAX_VALIDATORS: int = int(_env("WEALL_BOOTSTRAP_MAX_VALIDATORS", "100"))

    STAGE1_MAX: int = int(_env("WEALL_STAGE1_MAX", "10"))
    STAGE1_K: int = int(_env("WEALL_STAGE1_K", "1"))
    STAGE2_MAX: int = int(_env("WEALL_STAGE2_MAX", "50"))
    STAGE2_PCT: float = float(_env("WEALL_STAGE2_PCT", "0.33"))
    STAGE3_MAX: int = int(_env("WEALL_STAGE3_MAX", "100"))
    STAGE3_PCT: float = float(_env("WEALL_STAGE3_PCT", "0.50"))
    QUORUM_MODEL: str = _env("WEALL_QUORUM_MODEL", "bft_2f1")

    # ---------- Epoch / Rewards ----------
    EPOCH_DURATION_SEC: int = int(_env("WEALL_EPOCH_DURATION_SEC", "600"))

    # Block reward & pool split (even 5-way)
    BLOCK_REWARD: int = int(_env("WEALL_BLOCK_REWARD", "100"))  # units of WeCoin
    # 5 pools: validator, juror, storage, creator, treasury → each 20%
    POOL_SPLIT_VALIDATOR: float = 0.20
    POOL_SPLIT_JUROR: float = 0.20
    POOL_SPLIT_STORAGE: float = 0.20
    POOL_SPLIT_CREATOR: float = 0.20
    POOL_SPLIT_TREASURY: float = 0.20
