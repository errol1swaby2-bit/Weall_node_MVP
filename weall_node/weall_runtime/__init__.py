# weall_node/weall_runtime/__init__.py
from __future__ import annotations

"""
WeAll runtime package (lazy import / Termux-friendly)

Why:
- In Termux (and in general), import-time side effects cause pain.
- Proto TX lane should be able to load without pulling in heavy dependencies.
- Uvicorn / FastAPI import path should not explode because a deep module import
  triggered crypto/toolchain requirements.

This file intentionally does NOT import crypto/storage/etc at import time.

It provides:
- a small helper for "dev insecure crypto" flag
- lazy module attribute access via __getattr__ (PEP 562)
"""

from importlib import import_module
from typing import Any
import os

__all__ = [
    "is_dev_insecure_mode",
    # lazily exposed modules:
    "crypto",
    "storage",
    "ledger",
    "wallet",
    "roles",
    "poh",
    "poh_flow",
    "poh_sync",
    "sync",
    "reputation",
    "reputation_jurors",
    "governance",
    "disputes",
    "participation",
]

_DEV_INSECURE = os.getenv("WEALL_DEV_INSECURE_CRYPTO", "0") == "1"


def is_dev_insecure_mode() -> bool:
    return _DEV_INSECURE


_LAZY_MAP = {
    # historically: `from . import crypto_utils as crypto`
    "crypto": "weall_node.weall_runtime.crypto_utils",
    "storage": "weall_node.weall_runtime.storage",
    "ledger": "weall_node.weall_runtime.ledger",
    "wallet": "weall_node.weall_runtime.wallet",
    "roles": "weall_node.weall_runtime.roles",
    "poh": "weall_node.weall_runtime.poh",
    "poh_flow": "weall_node.weall_runtime.poh_flow",
    "poh_sync": "weall_node.weall_runtime.poh_sync",
    "sync": "weall_node.weall_runtime.sync",
    "reputation": "weall_node.weall_runtime.reputation",
    "reputation_jurors": "weall_node.weall_runtime.reputation_jurors",
    "governance": "weall_node.weall_runtime.governance",
    "disputes": "weall_node.weall_runtime.disputes",
    "participation": "weall_node.weall_runtime.participation",
}


def __getattr__(name: str) -> Any:
    mod_path = _LAZY_MAP.get(name)
    if not mod_path:
        raise AttributeError(name)
    return import_module(mod_path)


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(_LAZY_MAP.keys()))
