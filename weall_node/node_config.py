"""
weall_node/node_config.py
--------------------------------------------------
Node-level configuration for WeAll Node.

Introduces a single canonical concept:

    NODE_KIND: one of roles.NodeKind

Resolution order:

    1. Environment variable WEALL_NODE_KIND
       (one of: observer_client, public_gateway, validator_node, community_node)

    2. JSON file node_kind.json in the project root, shape:

        { "node_kind": "validator_node" }

    3. Fallback: PUBLIC_GATEWAY
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .weall_runtime import roles as runtime_roles

PROJECT_ROOT = Path(__file__).resolve().parent


def _from_env() -> runtime_roles.NodeKind | None:
    raw = os.getenv("WEALL_NODE_KIND")
    if not raw:
        return None
    raw = raw.strip().lower()
    for kind in runtime_roles.NodeKind:
        if kind.value == raw:
            return kind
    return None


def _from_file() -> runtime_roles.NodeKind | None:
    cfg_path = PROJECT_ROOT / "node_kind.json"
    if not cfg_path.exists():
        return None
    try:
        data = json.loads(cfg_path.read_text())
    except Exception:
        return None
    raw = str(data.get("node_kind", "")).strip().lower()
    for kind in runtime_roles.NodeKind:
        if kind.value == raw:
            return kind
    return None


def _resolve_node_kind() -> runtime_roles.NodeKind:
    env_kind = _from_env()
    if env_kind is not None:
        return env_kind
    file_kind = _from_file()
    if file_kind is not None:
        return file_kind
    # Default: gateway node that exposes HTTP API but does not
    # participate in consensus.
    return runtime_roles.NodeKind.PUBLIC_GATEWAY


NODE_KIND: runtime_roles.NodeKind = _resolve_node_kind()
