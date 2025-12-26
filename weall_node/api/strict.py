from __future__ import annotations

"""
Strict API mutation gates.

Goal:
- When WEALL_STRICT_API=1, ALL state-mutating REST endpoints require:
  - executor.strict_prod == True
  - AND, optionally, executor.dev_allow_unsigned == False (already enforced by strict_prod)
- This prevents the REST surface from mutating state in "dev-unsafe" mode.

You can run:
  export WEALL_STRICT_API=1
  export WEALL_STRICT_PROD=1
to fully lock it down.

For local dev, set WEALL_STRICT_API=0 (default).
"""

import os
from typing import Optional

from fastapi import HTTPException

from weall_node.weall_executor import executor


def strict_api_enabled() -> bool:
    return os.environ.get("WEALL_STRICT_API", "0").strip() == "1"


def require_mutation_allowed(user_id: Optional[str] = None) -> None:
    """
    Gatekeeper for any REST endpoint that changes state.
    """
    if not strict_api_enabled():
        return

    if not getattr(executor, "strict_prod", False):
        raise HTTPException(
            status_code=403,
            detail="strict_api_requires_strict_prod",
        )

    # In strict prod, signatures are required and unsigned is disabled by executor.
    # We keep this explicit check in case config drifts.
    if getattr(executor, "dev_allow_unsigned", True):
        raise HTTPException(
            status_code=403,
            detail="strict_api_unsigned_disabled",
        )

    # Optional: require auth in strict API mode (if your auth is wired)
    # If you later add real auth, this will become meaningful.
    if user_id is not None and str(user_id).strip() == "":
        raise HTTPException(status_code=401, detail="auth_required")
