"""
Consensus/genesis parameters, including Genesis Safeguard Mode (GSM).
"""
import json, os
from typing import Dict

GENESIS_PARAMS: Dict[str, object] = {}

DEFAULT_GENESIS = {
    "gsm_active": True,
    "gsm_expire_by_blocks": 2016,   # auto-disable after ~2 weeks if block time ~10m
    "gsm_expire_by_days": 14,
    "gsm_emergency_extra_jurors": 3,
    "poh_quorum_threshold": 10,     # unique Tier-3 jurors to auto-disable GSM
    "premine": []                   # optional, explicit premine allocations
}

def load_genesis_params(path: str = None) -> Dict[str, object]:
    """
    Load genesis parameters from a JSON file or fallback to defaults.
    """
    global GENESIS_PARAMS
    path = path or os.environ.get("WEALL_GENESIS_PARAMS", "genesis_params.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            GENESIS_PARAMS = json.load(f)
    else:
        GENESIS_PARAMS = DEFAULT_GENESIS.copy()
    return GENESIS_PARAMS
