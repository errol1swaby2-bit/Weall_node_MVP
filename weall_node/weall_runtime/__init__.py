# == DEV CRYPTO FALLBACK INSERTED ==
try:
    # Prefer the real implementation (requires pycryptodome: Crypto.Cipher.AES)
    from .crypto_symmetric import SimpleFernet as _RealSimpleFernet  # type: ignore
    SimpleFernet = _RealSimpleFernet
except Exception:  # ImportError or runtime env missing Crypto
    # Dev-only fallback: pure-Python shim to unblock local dev on low-end devices.
    from .crypto_symmetric_dev import SimpleFernet  # type: ignore
# == DEV CRYPTO FALLBACK INSERTED ==

# weall_node/weall_runtime/__init__.py
"""
Lightweight runtime modules used by WeAllExecutor.
All modules are pure-Python to keep Termux/Android installs simple.
"""

from .crypto_utils import (
    generate_keypair,
    sign_message,
    verify_ed25519_sig,
)
# from .crypto_symmetric import SimpleFernet  # disabled by fix: we require fallback logic
from .ledger import LedgerRuntime
from .governance import GovernanceRuntime, GLOBAL_PARAMS
from .poh import PoHRuntime
from .sync import BlockTimeScheduler

__all__ = [
    "generate_keypair",
    "sign_message",
    "verify_ed25519_sig",
    "SimpleFernet",
    "LedgerRuntime",
    "GovernanceRuntime",
    "GLOBAL_PARAMS",
    "PoHRuntime",
    "BlockTimeScheduler",
]

from .reputation import ReputationRuntime

try:
    __all__.append("ReputationRuntime")
except NameError:
    __all__ = ["ReputationRuntime"]
