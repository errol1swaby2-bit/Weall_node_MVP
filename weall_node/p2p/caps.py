from __future__ import annotations

import os
from typing import Any, Dict, List


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    v = str(v).strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int = 0) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _csv_env(name: str, default: List[str] | None = None) -> List[str]:
    v = os.getenv(name, "")
    items = [x.strip() for x in v.split(",") if x.strip()]
    if items:
        return items
    return list(default or [])


def build_self_capabilities() -> Dict[str, Any]:
    """
    Capability schema is intentionally small and JSON-friendly.
    Stored under peer.meta["caps"].

    Env vars (all optional):
      WEALL_CAPS_OPERATOR=1
      WEALL_CAPS_VALIDATOR=0
      WEALL_CAPS_FULL=0                # convenience: implies operator+validator
      WEALL_CAPS_IPFS_PIN=1
      WEALL_CAPS_VIDEO_GATEWAY=1       # "I can serve video efficiently" (HLS, cached segments, etc.)
      WEALL_CAPS_HLS=1                 # "I can serve HLS playlists/segments"
      WEALL_CAPS_SUPPORTS=feed,upload,governance,webrtc
      WEALL_CAPS_REGION=us-west
      WEALL_CAPS_BANDWIDTH_KBPS=20000
      WEALL_CAPS_STORAGE_MB=51200
    """
    full = _bool_env("WEALL_CAPS_FULL", False)
    operator = _bool_env("WEALL_CAPS_OPERATOR", False) or full
    validator = _bool_env("WEALL_CAPS_VALIDATOR", False) or full

    caps: Dict[str, Any] = {
        "operator": bool(operator),
        "validator": bool(validator),
        "full": bool(full),
        "ipfs_pin": _bool_env("WEALL_CAPS_IPFS_PIN", False),
        "video_gateway": _bool_env("WEALL_CAPS_VIDEO_GATEWAY", False),
        "hls": _bool_env("WEALL_CAPS_HLS", False),
        "supports": _csv_env("WEALL_CAPS_SUPPORTS", default=["governance"]),
        "region": os.getenv("WEALL_CAPS_REGION", "").strip(),
        "bandwidth_kbps": _int_env("WEALL_CAPS_BANDWIDTH_KBPS", 0),
        "storage_mb": _int_env("WEALL_CAPS_STORAGE_MB", 0),
    }

    # Clean up empty fields
    if not caps["region"]:
        caps.pop("region", None)
    if not caps.get("supports"):
        caps["supports"] = ["governance"]

    return caps


def supports_purpose(peer_meta: Dict[str, Any], purpose: str) -> bool:
    """
    Checks whether a peer claims to support a given purpose.
    """
    if not isinstance(peer_meta, dict):
        return False
    caps = peer_meta.get("caps")
    if not isinstance(caps, dict):
        return False
    supp = caps.get("supports")
    if not isinstance(supp, list):
        return False
    purpose = (purpose or "").strip().lower()
    return purpose in {str(x).strip().lower() for x in supp if x}
