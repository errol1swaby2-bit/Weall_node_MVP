# weall_node/weall_runtime/__init__.py
from __future__ import annotations

"""
WeAll runtime facade.

This package groups the low-level runtime helpers used by the node:

- storage         : content storage helpers (IPFS / in-memory fallback)
- participation   : juror/participant selection + randomness
- governance      : runtime governance / policy defaults
- utils           : misc helpers (timestamps, hashing, etc.)
- crypto          : Ed25519 + KDF + messaging wrappers
- crypto_symmetric: AES-GCM symmetric crypto implementation

Symmetric crypto backends
-------------------------
By default, all symmetric crypto should use the AES-GCM implementation
in `crypto_symmetric.py`.

An older, pycryptodome-based dev module (`crypto_symmetric_dev.py`)
still exists for experimentation and backwards compatibility on some
Termux-style environments, but it is *not* imported automatically for
production.

To explicitly allow the legacy / dev symmetric backend in a local dev
environment, set:

    WEALL_DEV_INSECURE_CRYPTO=1

before starting the node.

This flag should NEVER be enabled in production.
"""

import os

from . import storage
from . import participation
from . import governance
from . import utils
from . import crypto_utils as crypto
from . import crypto_symmetric
from .reputation import ReputationRuntime
from . import reputation_jurors

# ---------------------------------------------------------------------------
# Optional dev-only symmetric backend
# ---------------------------------------------------------------------------


DEV_INSECURE_CRYPTO: bool = bool(os.getenv("WEALL_DEV_INSECURE_CRYPTO"))

if DEV_INSECURE_CRYPTO:
    try:
        # Legacy / dev-only symmetric implementation (pycryptodome / Crypto.Cipher)
        from . import crypto_symmetric_dev  # type: ignore
    except Exception:  # pragma: no cover - dev-only import failure
        crypto_symmetric_dev = None  # type: ignore
else:
    # Expose the name but make it clear it's disabled
    crypto_symmetric_dev = None  # type: ignore


def is_dev_insecure_mode() -> bool:
    """
    Return True if the process is explicitly configured to allow the
    legacy / insecure symmetric crypto backend.

    This is primarily useful for diagnostics. Runtime code should still
    prefer `crypto_symmetric` (AES-GCM) for all real encryption.
    """
    return DEV_INSECURE_CRYPTO
