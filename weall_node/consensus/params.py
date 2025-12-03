"""
weall_node/consensus/params.py
------------------------------

Genesis / consensus parameters for WeAll.

This module centralizes network-wide constants like:

- Genesis time
- GSM (Genesis Safeguard Mode) settings
- Minimum validators
- Block / epoch schedule
- Monetary policy hints for the WeCoin ledger
- Pool split defaults

The values defined here are **sane defaults** suitable for local dev and
single-node testing.  They can be overridden via a JSON file whose path is
provided either explicitly to `load_genesis_params(path=...)` or via the
`WEALL_GENESIS_PARAMS` environment variable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import json
import os
import time

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# For dev: use a fixed-ish genesis time if not overridden, so different
# nodes that start at roughly the same moment still share a common reference.
_DEFAULT_GENESIS_TIME: int = int(os.environ.get("WEALL_GENESIS_TIME", str(int(time.time()))))

DEFAULT_GENESIS: Dict[str, Any] = {
    # When the chain "starts" (seconds since Unix epoch)
    "genesis_time": _DEFAULT_GENESIS_TIME,
    # Genesis Safeguard Mode: if true, validators are limited / pre-set
    # and rewards may be routed more conservatively (e.g., to treasury).
    "gsm_active": False,
    # Minimum number of validators required for normal operation
    "min_validators": 1,
    # Target blocks per epoch (used for epoch events & analytics only)
    # At 10 minutes per block, 1008 ≈ one week.
    "blocks_per_epoch": 1008,
    # Monetary policy hints (WeCoin ledger still enforces the hard cap internally)
    "block_interval_seconds": 600,             # 10 minutes
    "initial_block_reward": 100.0,             # WCN per block at genesis
    "halving_interval_seconds": 2 * 365 * 24 * 60 * 60,  # 2 years
    "max_supply": 21_000_000.0,
    # Default pool split – should match weall_runtime.ledger.DEFAULT_POOL_SPLIT
    "pool_split": {
        "validators": 0.20,
        "jurors": 0.20,
        "creators": 0.20,
        "operators": 0.20,
        "treasury": 0.20,
    },
}

GENESIS_CACHE: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_from_disk(path: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON loader for genesis parameters."""
    if not path:
        return None
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        # Shallow-validate keys we know about; ignore unknown keys.
        out: Dict[str, Any] = {}
        for k, v in data.items():
            out[str(k)] = v
        return out
    except Exception:
        # Never let genesis loading crash the node – just fall back to defaults.
        return None


def load_genesis_params(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load genesis parameters from JSON, merged over DEFAULT_GENESIS.

    Resolution order:
        1. Explicit `path` argument (if provided)
        2. WEALL_GENESIS_PARAMS env var (if set)
        3. "genesis_params.json" in CWD (if it exists)
        4. DEFAULT_GENESIS (in-memory defaults)

    Disk parameters, when present, overwrite DEFAULT_GENESIS.
    """
    global GENESIS_CACHE
    if GENESIS_CACHE is not None:
        return GENESIS_CACHE

    # Resolve the path that should be consulted (if any)
    resolved_path: Optional[str] = path
    if not resolved_path:
        env_path = os.environ.get("WEALL_GENESIS_PARAMS")
        if env_path:
            resolved_path = env_path
        else:
            candidate = os.path.join(os.getcwd(), "genesis_params.json")
            if os.path.exists(candidate):
                resolved_path = candidate

    disk_params: Optional[Dict[str, Any]] = None
    if resolved_path:
        disk_params = _load_from_disk(resolved_path)

    merged: Dict[str, Any] = dict(DEFAULT_GENESIS)
    for key, value in (disk_params or {}).items():
        merged[key] = value

    GENESIS_CACHE = merged
    return merged
