"""weall_node/node_config.py

Node-level configuration (Spec v2 friendly)
------------------------------------------

This module intentionally stays **side-effect light** and is import-safe.
It provides:

  - NODE_KIND        : intended topology role for this node
  - VALIDATORS       : static validator allowlist (dev + GSM)
  - QUORUM_FRACTION  : quorum threshold for PBFT-lite voting

Resolution order (NODE_KIND)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1) Environment variable WEALL_NODE_KIND
   One of: observer_client, public_gateway, validator_node, community_node

2) JSON file "node_kind.json" in the repo root (PROJECT_ROOT)

3) Fallback: public_gateway

Resolution order (VALIDATORS / QUORUM_FRACTION)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1) Environment variables:
     WEALL_VALIDATORS       comma-separated list of validator node ids
     WEALL_QUORUM_FRACTION  float like 0.6

2) JSON file "validators.json" in the repo root:
     {
       "validators": ["<node_id>", "<other_node_id>", ...],
       "quorum_fraction": 0.6
     }

3) Fallback: [local node_id] (single-node dev), quorum_fraction=0.60

Notes
-----
- node_id is loaded from WEALL_DATA_DIR/node_id.json first (runtime-local).
  Legacy repo-root node_id.json is only a fallback for compatibility.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from .weall_runtime import roles as runtime_roles


# Repo root = parent of the package directory (weall_node/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Default data dir (matches weall_node/settings.py)
DATA_DIR = Path(os.getenv("WEALL_DATA_DIR", str(PROJECT_ROOT / "data")))


def _read_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# NODE_KIND
# ---------------------------------------------------------------------------


def _from_env_node_kind() -> Optional[runtime_roles.NodeKind]:
    raw = os.getenv("WEALL_NODE_KIND")
    if not raw:
        return None
    raw = raw.strip().lower()
    for kind in runtime_roles.NodeKind:
        if kind.value == raw:
            return kind
    return None


def _from_file_node_kind() -> Optional[runtime_roles.NodeKind]:
    data = _read_json(PROJECT_ROOT / "node_kind.json")
    if not data:
        return None
    raw = str(data.get("node_kind", "")).strip().lower()
    for kind in runtime_roles.NodeKind:
        if kind.value == raw:
            return kind
    return None


def _resolve_node_kind() -> runtime_roles.NodeKind:
    env_kind = _from_env_node_kind()
    if env_kind is not None:
        return env_kind
    file_kind = _from_file_node_kind()
    if file_kind is not None:
        return file_kind
    return runtime_roles.NodeKind.PUBLIC_GATEWAY


NODE_KIND: runtime_roles.NodeKind = _resolve_node_kind()


# ---------------------------------------------------------------------------
# VALIDATORS + QUORUM_FRACTION
# ---------------------------------------------------------------------------


def _read_node_id() -> Optional[str]:
    """Best-effort read of node_id.json.

    Preferred location is the runtime data dir (WEALL_DATA_DIR / node_id.json).
    For backward compatibility, we also try the legacy repo-root node_id.json.
    """
    # Preferred (runtime-local) location
    data = _read_json(DATA_DIR / "node_id.json")
    if not data:
        # Legacy fallback (do NOT ship secrets here)
        data = _read_json(PROJECT_ROOT / "node_id.json")
    if not data:
        return None
    nid = str(data.get("node_id") or "").strip()
    return nid or None


def _validators_from_env() -> Optional[List[str]]:
    raw = os.getenv("WEALL_VALIDATORS")
    if not raw:
        return None
    vals = [v.strip() for v in raw.split(",") if v.strip()]
    return vals or None


def _quorum_from_env() -> Optional[float]:
    raw = os.getenv("WEALL_QUORUM_FRACTION")
    if not raw:
        return None
    try:
        q = float(raw)
        return max(0.0, min(1.0, q))
    except Exception:
        return None


def _validators_from_file() -> tuple[Optional[List[str]], Optional[float]]:
    data = _read_json(PROJECT_ROOT / "validators.json")
    if not data:
        return None, None
    vals = data.get("validators")
    validators: Optional[List[str]] = None
    if isinstance(vals, list):
        validators = [str(v).strip() for v in vals if str(v).strip()]
        validators = validators or None
    quorum = data.get("quorum_fraction")
    quorum_f: Optional[float] = None
    if quorum is not None:
        try:
            quorum_f = max(0.0, min(1.0, float(quorum)))
        except Exception:
            quorum_f = None
    return validators, quorum_f


_env_validators = _validators_from_env()
_env_quorum = _quorum_from_env()
_file_validators, _file_quorum = _validators_from_file()


def _dedup(vals: List[str]) -> List[str]:
    seen = set()
    out = []
    for v in vals:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


VALIDATORS: List[str] = _dedup(
    _env_validators
    or _file_validators
    or ([(_read_node_id() or "")] if _read_node_id() else [])
)

# Spec v2 default for voting quorum is 60%
QUORUM_FRACTION: float = float(
    _env_quorum if _env_quorum is not None else (_file_quorum if _file_quorum is not None else 0.60)
)
