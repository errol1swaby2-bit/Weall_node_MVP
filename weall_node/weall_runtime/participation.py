"""
weall_node/weall_runtime/participation.py
-----------------------------------------
Participation / role selection helpers for WeAll Node.

Implements spec-aligned selection for:
- Juror panels (Tier-3 PoH, not revoked)
- Validator candidates (Tier-3 PoH, not revoked)

Design goals:
- Deterministic: same inputs → same panel
- Reputation-aware: higher rep slightly preferred
- Simple & auditable: pure functions, no hidden state

This module does NOT reach into the executor directly.
Instead, it operates on plain dicts so that callers can
adapt to the current ledger layout.
"""

from __future__ import annotations

import hashlib
from typing import Dict, Any, List


def _norm_reputation(rep_score: float) -> float:
    """
    Normalize reputation score from [-1, 1] → [0, 1].

    Values outside [-1, 1] are clamped.
    """
    s = max(-1.0, min(1.0, rep_score))
    return (s + 1.0) / 2.0


def _deterministic_noise(seed: str, user_id: str) -> float:
    """
    Produce a deterministic pseudo-random float in [0, 1)
    based on (seed, user_id).

    This avoids using global RNG and keeps selection verifiable.
    """
    h = hashlib.sha256()
    h.update(seed.encode("utf-8"))
    h.update(b":")
    h.update(user_id.encode("utf-8"))
    digest = h.digest()
    # Use first 8 bytes as big-endian integer
    n = int.from_bytes(digest[:8], "big")
    return (n % (10**8)) / float(10**8)


def _build_candidate_score(
    user_id: str,
    rep_scores: Dict[str, float],
    seed: str,
    base_weight: float = 0.7,
) -> float:
    """
    Compute a selection score for a user, combining:

    - Normalized reputation (0..1)
    - Deterministic noise from (seed, user_id)

    base_weight controls how much reputation matters vs the noise.
    """
    rep_norm = _norm_reputation(rep_scores.get(user_id, 0.0))
    noise = _deterministic_noise(seed, user_id)
    # Weighted blend, reputation in [0,1], noise in [0,1]
    return base_weight * rep_norm + (1.0 - base_weight) * noise


def select_juror_panel(
    poh_records: Dict[str, Any],
    reputation: Dict[str, float],
    case_id: str,
    required: int,
    min_tier: int = 3,
) -> List[str]:
    """
    Select a juror panel from PoH records.

    Arguments:
        poh_records: mapping user_id -> PoH record dict.
                     Expected keys on each record:
                       - "tier": int
                       - "revoked": bool (optional, default False)
        reputation:  mapping user_id -> float in [-1, 1] (optional).
        case_id:     unique identifier for this dispute/case. Used
                     as a deterministic seed.
        required:    number of jurors to select.
        min_tier:    minimum PoH tier required to serve as juror
                     (default: 3).

    Returns:
        List of user_ids chosen deterministically from eligible pool.
        If there are fewer eligible than required, returns all eligible.
    """
    if required <= 0:
        return []

    # 1. Filter eligible candidates
    eligible: List[str] = []
    for user_id, rec in poh_records.items():
        try:
            tier = int(rec.get("tier", 0))
        except Exception:
            tier = 0
        revoked = bool(rec.get("revoked", False))
        if tier >= min_tier and not revoked:
            eligible.append(user_id)

    if not eligible:
        return []

    if len(eligible) <= required:
        # Nothing to rank; everyone eligible is in the panel
        return sorted(eligible)

    # 2. Compute scores
    scored = []
    for uid in eligible:
        score = _build_candidate_score(uid, reputation, seed=case_id)
        scored.append((score, uid))

    # 3. Sort by score descending, then user_id to keep deterministic
    scored.sort(key=lambda x: (-x[0], x[1]))

    # 4. Take top-N
    panel = [uid for _, uid in scored[:required]]
    return panel


def select_validator_candidates(
    poh_records: Dict[str, Any],
    reputation: Dict[str, float],
    epoch_id: str,
    max_validators: int,
    min_tier: int = 3,
) -> List[str]:
    """
    Select a set of validator candidates for a given epoch.

    This mirrors juror selection but is keyed on epoch_id instead
    of a dispute/case ID.

    For now, the logic is identical to juror selection; the executor
    or consensus module can then choose a subset or rotate among them.

    Arguments:
        poh_records: mapping user_id -> PoH record dict.
        reputation:  mapping user_id -> float in [-1, 1].
        epoch_id:    deterministic seed (e.g., "epoch:42").
        max_validators: maximum number of validators to select.
        min_tier:    minimum PoH tier required (default: 3).

    Returns:
        List of user_ids chosen deterministically.
    """
    if max_validators <= 0:
        return []

    # Reuse selection logic with a different seed
    candidates = select_juror_panel(
        poh_records=poh_records,
        reputation=reputation,
        case_id=epoch_id,
        required=max_validators,
        min_tier=min_tier,
    )
    return candidates
