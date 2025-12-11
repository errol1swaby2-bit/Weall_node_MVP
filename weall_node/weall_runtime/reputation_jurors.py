"""
weall_node/weall_runtime/reputation_jurors.py
-------------------------------------------

Lightweight adapter for juror reputation constants.

Historically the juror reputation thresholds lived in a separate module.
The current implementation stores juror metadata under:

    ledger["reputation"]["jurors"][user_id] = {
        "score": int,
        "opt_in": bool,
        "strikes": int,
    }

and defines the minimum juror score directly in `disputes.MIN_JUROR_SCORE`.

To keep the tests and any external callers stable, we expose the same
constant here and re-export it from the runtime package.

This module is intentionally tiny; all real logic lives in
`weall_node.weall_runtime.disputes`.
"""

from __future__ import annotations

from .disputes import MIN_JUROR_SCORE

__all__ = ["MIN_JUROR_SCORE"]
