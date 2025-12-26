from __future__ import annotations

"""
State compaction + pruning rules.

This module defines a single function:
  compact_ledger_in_place(ledger, *, policy) -> stats

Policy is intentionally simple:
- Keep last N blocks in full (including tx b64)
- Keep tx_index always (cheap)
- Prune tx_receipts older than N blocks if desired
- Prune events older than M
- Optional: strip mempool contents on start (safety)

This keeps the snapshot small while preserving enough history for audit & debugging.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class CompactionPolicy:
    keep_recent_blocks: int = 200
    keep_events: int = 2000
    prune_tx_receipts: bool = True
    keep_receipts_for_blocks: int = 200
    drop_mempool: bool = False


def _ensure_dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _ensure_list(x: Any) -> list:
    return x if isinstance(x, list) else []


def compact_ledger_in_place(ledger: Dict[str, Any], *, policy: Optional[CompactionPolicy] = None) -> Dict[str, Any]:
    p = policy or CompactionPolicy()
    stats = {"ok": True, "pruned_blocks": 0, "pruned_events": 0, "pruned_receipts": 0, "mempool_dropped": False}

    chain = _ensure_list(ledger.get("chain"))
    if not isinstance(chain, list):
        chain = []
    height = len(chain)

    # Prune chain history (keep last N blocks)
    keep_n = max(0, int(p.keep_recent_blocks))
    if keep_n > 0 and height > keep_n:
        cut = height - keep_n
        ledger["chain"] = chain[cut:]
        stats["pruned_blocks"] = int(cut)

        # Note: tx_index can remain; it’s small and helps debugging.
        # If you later want to prune tx_index too, do it by height.

    # Prune events
    events = _ensure_list(ledger.get("events"))
    keep_e = max(0, int(p.keep_events))
    if keep_e > 0 and len(events) > keep_e:
        cut = len(events) - keep_e
        ledger["events"] = events[cut:]
        stats["pruned_events"] = int(cut)

    # Drop mempool on demand (safe startup option)
    if p.drop_mempool:
        ledger["mempool"] = {"order": [], "by_id": {}}
        stats["mempool_dropped"] = True

    # Prune tx_receipts by block height window
    if p.prune_tx_receipts:
        tx_index = _ensure_dict(ledger.get("tx_index"))
        tx_receipts = _ensure_dict(ledger.get("tx_receipts"))
        if isinstance(tx_index, dict) and isinstance(tx_receipts, dict) and tx_receipts:
            # Determine minimum kept height
            keep_blocks = max(0, int(p.keep_receipts_for_blocks))
            if keep_blocks > 0:
                min_height = max(0, height - keep_blocks)
                # tx_index stores heights for tx_ids. Remove receipts for txs < min_height.
                to_delete = []
                for tx_id, meta in tx_index.items():
                    if not isinstance(meta, dict):
                        continue
                    try:
                        h = int(meta.get("height", 0) or 0)
                    except Exception:
                        h = 0
                    if h < min_height and tx_id in tx_receipts:
                        to_delete.append(tx_id)
                for tx_id in to_delete:
                    del tx_receipts[tx_id]
                stats["pruned_receipts"] = int(len(to_delete))

            ledger["tx_receipts"] = tx_receipts

    return stats
