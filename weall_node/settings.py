from __future__ import annotations

import os
from typing import List


def _csv(name: str, default: List[str] | None = None) -> List[str]:
    raw = os.getenv(name, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items if items else list(default or [])


class Settings:
    # P2P / operator config
    P2P_ENABLED: bool = True

    P2P_BOOTSTRAP: str = os.getenv("WEALL_P2P_BOOTSTRAP", "")
    P2P_SELF_ADDR: str = os.getenv("WEALL_P2P_SELF_ADDR", "").strip()

    P2P_GOSSIP_INTERVAL_SEC: int = int(os.getenv("WEALL_P2P_GOSSIP_INTERVAL_SEC", "30"))
    P2P_PEX_FANOUT: int = int(os.getenv("WEALL_P2P_PEX_FANOUT", "4"))
    P2P_MAX_PEERS: int = int(os.getenv("WEALL_P2P_MAX_PEERS", "256"))
    P2P_HTTP_TIMEOUT_SEC: float = float(os.getenv("WEALL_P2P_HTTP_TIMEOUT_SEC", "2.5"))

    # Client rotation defaults (served via /p2p/client_config)
    CLIENT_PICK_K: int = int(os.getenv("WEALL_CLIENT_PICK_K", "10"))
    CLIENT_REFRESH_SEC: int = int(os.getenv("WEALL_CLIENT_REFRESH_SEC", "180"))
    CLIENT_TIMEOUT_MS: int = int(os.getenv("WEALL_CLIENT_TIMEOUT_MS", "2500"))
    CLIENT_FAIL_COOLDOWN_SEC: int = int(os.getenv("WEALL_CLIENT_FAIL_COOLDOWN_SEC", "60"))
    CLIENT_MAX_POOL: int = int(os.getenv("WEALL_CLIENT_MAX_POOL", "64"))

    # Identity / storage
    DATA_DIR: str = os.getenv("WEALL_DATA_DIR", "data")

    # Capability defaults (used by p2p.caps)
    CAPS_SUPPORTS: List[str] = _csv("WEALL_CAPS_SUPPORTS", default=["governance"])


settings = Settings()
