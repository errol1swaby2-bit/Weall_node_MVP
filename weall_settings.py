# weall_settings.py
from __future__ import annotations
from pathlib import Path
from functools import lru_cache
from typing import List, Optional, Literal, Any
import os, secrets, yaml
from pydantic import BaseModel, Field, validator

# -------------------------
# Pydantic models (typed)
# -------------------------


class PersistenceConf(BaseModel):
    driver: Literal["json", "sqlite"] = "json"
    sqlite_path: str = "weall.db"  # used only when driver == "sqlite"


class IPFSConf(BaseModel):
    require_ipfs: bool = False


class GovernanceConf(BaseModel):
    tier3_quorum_fraction: float = 0.6
    tier3_yes_fraction: float = 0.5


class ChainConf(BaseModel):
    block_max_txs: int = 1000


class SecurityConf(BaseModel):
    require_signed_votes: bool = True
    require_signed_tx: bool = False


class LoggingConf(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json: bool = True


class RuntimeConf(BaseModel):
    editable_roots: List[str] = Field(
        default_factory=lambda: ["weall_node", "frontend", "pallets", "runtime"]
    )
    backup_dir: str = ".weall_backups"


class EmailConf(BaseModel):
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = "YOUR_SMTP_EMAIL@gmail.com"
    smtp_pass: str = "YOUR_APP_PASSWORD"
    from_name: str = "WeAll Network"
    from_email: str = "no-reply@weall.network"
    use_tls: bool = True


# Optional (additive) sections with safe defaults
class ServerConf(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])


class JWTConf(BaseModel):
    secret_key: Optional[str] = None  # if None, we generate ephemeral (dev)
    algorithm: str = "HS256"
    expire_minutes: int = 60


class Settings(BaseModel):
    # Core (your YAML)
    persistence: PersistenceConf = PersistenceConf()
    ipfs: IPFSConf = IPFSConf()
    governance: GovernanceConf = GovernanceConf()
    chain: ChainConf = ChainConf()
    security: SecurityConf = SecurityConf()
    logging: LoggingConf = LoggingConf()
    runtime: RuntimeConf = RuntimeConf()
    email: EmailConf = EmailConf()

    # Optional (we allow these to exist only in env or be omitted in YAML)
    server: ServerConf = ServerConf()
    jwt: JWTConf = JWTConf()

    # Derived fields (computed in finalize)
    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data"
    STATE_FILE: Path = BASE_DIR / "weall_state.json"  # used when driver == "json"
    SQLITE_PATH: Path = BASE_DIR / "weall.db"
    SQLITE_URL: str = "sqlite:///"  # filled in finalize

    def finalize(self) -> "Settings":
        base = Path(os.getenv("WEALL_BASE_DIR", self.BASE_DIR))
        # data dir (env override)
        data_dir = Path(os.getenv("WEALL_DATA_DIR", base / "data"))
        if not data_dir.is_absolute():
            data_dir = base / data_dir
        self.DATA_DIR = data_dir
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        # persistence paths
        self.SQLITE_PATH = Path(self.persistence.sqlite_path)
        if not self.SQLITE_PATH.is_absolute():
            self.SQLITE_PATH = self.DATA_DIR / self.SQLITE_PATH
        self.SQLITE_URL = f"sqlite:///{self.SQLITE_PATH}"

        # default JSON state file when driver=json
        self.STATE_FILE = self.DATA_DIR / "weall_state.json"

        # ephemeral secret unless provided
        if not self.jwt.secret_key:
            self.jwt.secret_key = os.getenv(
                "WEALL_JWT_SECRET"
            ) or secrets.token_urlsafe(32)

        # env overrides for server
        self.server.host = os.getenv("WEALL_HOST", self.server.host)
        self.server.port = int(os.getenv("WEALL_PORT", self.server.port))
        # allow comma list for CORS
        cors_env = os.getenv("WEALL_CORS_ORIGINS")
        if cors_env:
            self.server.cors_origins = [
                x.strip() for x in cors_env.split(",") if x.strip()
            ]

        # env override for IPFS multiaddr (if you later add ipfs.api)
        # e.g., WEALL_IPFS_API=/ip4/127.0.0.1/tcp/5001/http

        return self


# -------------------------
# YAML load + env overlay
# -------------------------


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _apply_env_overrides(cfg: dict) -> dict:
    # Only minimal mapping; extend as needed
    def set_in(keys: List[str], value: Any):
        d = cfg
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    if os.getenv("WEALL_PERSISTENCE_DRIVER"):
        set_in(["persistence", "driver"], os.getenv("WEALL_PERSISTENCE_DRIVER"))
    if os.getenv("WEALL_SQLITE_PATH"):
        set_in(["persistence", "sqlite_path"], os.getenv("WEALL_SQLITE_PATH"))

    if os.getenv("WEALL_REQUIRE_IPFS"):
        set_in(
            ["ipfs", "require_ipfs"],
            os.getenv("WEALL_REQUIRE_IPFS").lower() in ("1", "true", "yes"),
        )

    if os.getenv("WEALL_JWT_SECRET"):
        set_in(["jwt", "secret_key"], os.getenv("WEALL_JWT_SECRET"))
    if os.getenv("WEALL_JWT_MIN"):
        set_in(["jwt", "expire_minutes"], int(os.getenv("WEALL_JWT_MIN")))

    if os.getenv("WEALL_HOST"):
        set_in(["server", "host"], os.getenv("WEALL_HOST"))
    if os.getenv("WEALL_PORT"):
        set_in(["server", "port"], int(os.getenv("WEALL_PORT")))

    if os.getenv("WEALL_LOG_LEVEL"):
        set_in(["logging", "level"], os.getenv("WEALL_LOG_LEVEL"))
    if os.getenv("WEALL_LOG_JSON"):
        set_in(
            ["logging", "json"],
            os.getenv("WEALL_LOG_JSON").lower() in ("1", "true", "yes"),
        )

    if os.getenv("WEALL_DATA_DIR"):
        # handled in finalize (path), but we keep a copy in cfg for visibility
        set_in(["runtime", "data_dir"], os.getenv("WEALL_DATA_DIR"))

    return cfg


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base = Path(__file__).resolve().parent
    yaml_path = Path(os.getenv("WEALL_CONFIG") or (base / "weall_config.yaml"))
    cfg = _load_yaml(yaml_path)
    cfg = _apply_env_overrides(cfg)
    settings = Settings(**cfg).finalize()
    return settings


# Convenience singleton
settings = get_settings()
