"""
weall_node/weall_runtime/ledger.py
----------------------------------

WeCoin monetary policy + reward distribution for WeAll.

Implements a Bitcoin-inspired schedule:

- MAX_SUPPLY = 21,000,000 WCN
- INITIAL_BLOCK_REWARD = 100 WCN
- BLOCK_INTERVAL_SECONDS = 600s (10 minutes)
- HALVING every HALVING_INTERVAL_SECONDS (~2 years by default)

Rewards are applied **per block**. For each block, the total block
reward is split evenly across the five reward pools:

    validators, jurors, creators, operators, treasury

Within each pool, a weighted lottery picks one winner based on tickets
recorded during that block/epoch.

This module is intentionally self-contained and pure-Python so it can
run on low-end Termux / Android devices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import math
import random

# ---------------------------------------------------------------------------
# Monetary policy constants
# ---------------------------------------------------------------------------

TREASURY_ACCOUNT: str = "treasury"

# Total coin supply (WeCoin) – capped like Bitcoin.
MAX_SUPPLY: float = 21_000_000.0

# Per-block base reward before halvings.
INITIAL_BLOCK_REWARD: float = 100.0

# Target time per block (10 minutes).
BLOCK_INTERVAL_SECONDS: int = 600

# Time between halvings (~2 years) and equivalent blocks-per-halving.
HALVING_INTERVAL_SECONDS: int = 2 * 365 * 24 * 60 * 60  # 2 years
BLOCKS_PER_HALVING: int = max(1, HALVING_INTERVAL_SECONDS // BLOCK_INTERVAL_SECONDS)

# ---------------------------------------------------------------------------
# Backwards-compat exports
# ---------------------------------------------------------------------------

# These names are imported by older modules (api/chain.py, etc.).  We keep
# them as aliases so those modules continue to work without modification.
INITIAL_EPOCH_REWARD: float = INITIAL_BLOCK_REWARD
HALVING_INTERVAL: int = HALVING_INTERVAL_SECONDS

# Default pool split (must sum to 1.0)
DEFAULT_POOL_SPLIT: Dict[str, float] = {
    "validators": 0.20,
    "jurors": 0.20,
    "creators": 0.20,
    "operators": 0.20,
    "treasury": 0.20,
}


def _normalize_pool_split(split: Dict[str, float]) -> Dict[str, float]:
    """Normalize pool split so that all values are >=0 and sum to 1.0."""
    cleaned: Dict[str, float] = {}
    total = 0.0
    for k, v in (split or {}).items():
        try:
            fv = float(v)
        except Exception:
            continue
        if fv <= 0:
            continue
        cleaned[str(k)] = fv
        total += fv
    if total <= 0:
        # Fall back to an even 20% split if bad config
        return dict(DEFAULT_POOL_SPLIT)
    for k in list(cleaned.keys()):
        cleaned[k] = cleaned[k] / total
    return cleaned


@dataclass
class WeCoinLedger:
    """
    Core WeCoin ledger.

    Tracks:
    - balances: account_id -> float
    - pool_split: reward pool -> fraction of each block reward
    - pools: reward pool -> {"members": set(account_ids)}
    - tickets: reward pool -> {account_id -> weight} for the *next* lottery
    - total_issued: running total of all WeCoin ever minted

    Public entrypoints used by the executor:

        add_ticket(pool, account_id, weight)
        clear_tickets()
        current_epoch_reward()
        distribute_epoch_rewards(epoch, bootstrap_mode=False)
        distribute_block_rewards(block_height, epoch, blocks_per_epoch, bootstrap_mode=False)
    """

    # Monetary policy (can be overridden in tests or by future genesis wiring)
    max_supply: float = MAX_SUPPLY
    initial_block_reward: float = INITIAL_BLOCK_REWARD
    blocks_per_halving: int = BLOCKS_PER_HALVING

    # Pool configuration
    pool_split: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_POOL_SPLIT))

    # State
    balances: Dict[str, float] = field(default_factory=dict)
    pools: Dict[str, Dict[str, set]] = field(
        default_factory=lambda: {name: {"members": set()} for name in DEFAULT_POOL_SPLIT.keys()}
    )
    tickets: Dict[str, Dict[str, float]] = field(
        default_factory=lambda: {name: {} for name in DEFAULT_POOL_SPLIT.keys()}
    )
    total_issued: float = 0.0
    last_block_height: int = -1
    blocks_per_epoch: int = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_pool_split(self, split: Dict[str, float]) -> None:
        """Override the pool split (values will be normalized to sum to 1.0)."""
        normalized = _normalize_pool_split(split)
        self.pool_split = normalized

        # Ensure pools/tickets dictionaries cover the same keys
        for name in list(self.pools.keys()):
            if name not in normalized:
                self.pools.pop(name, None)
        for name in list(self.tickets.keys()):
            if name not in normalized:
                self.tickets.pop(name, None)
        for name in normalized.keys():
            self.pools.setdefault(name, {"members": set()})
            self.tickets.setdefault(name, {})

    def _ensure_pool(self, pool: str) -> None:
        if pool not in self.pool_split:
            return
        self.pools.setdefault(pool, {"members": set()})
        self.tickets.setdefault(pool, {})

    def add_ticket(self, pool: str, account_id: str, weight: float = 1.0) -> None:
        """
        Add a weighted ticket for an account in a given pool for the current lottery.

        Called by the executor (validators) and, later, by PoH / content / operators.
        """
        if not account_id:
            return
        if pool not in self.pool_split:
            return

        self._ensure_pool(pool)
        tickets = self.tickets[pool]
        tickets[account_id] = tickets.get(account_id, 0.0) + max(0.0, float(weight))

    def clear_tickets(self) -> None:
        """Reset tickets for all pools after a distribution round."""
        for name in list(self.tickets.keys()):
            self.tickets[name] = {}

    # ------------------------------------------------------------------
    # Monetary policy helpers
    # ------------------------------------------------------------------

    def _current_block_reward(self, block_height: int) -> float:
        """
        Compute the base reward for a given block height, applying halvings.

        Halvings occur every `blocks_per_halving` blocks.  After N halvings,
        the reward is INITIAL_BLOCK_REWARD / 2**N.
        """
        if self.total_issued >= self.max_supply:
            return 0.0

        height = max(0, int(block_height))
        blocks_per_halving = max(1, int(self.blocks_per_halving or 1))
        halvings = height // blocks_per_halving
        reward = self.initial_block_reward / float(2 ** int(halvings))

        if reward <= 0.0:
            return 0.0

        remaining = max(0.0, self.max_supply - self.total_issued)
        if reward > remaining:
            reward = remaining
        return reward

    def current_epoch_reward(self) -> float:
        """
        Backwards-compat helper for API modules that want a single number.

        Approximate the epoch reward as:
            epoch_reward ≈ current_block_reward * blocks_per_epoch

        This method **does not** mutate state.
        """
        if self.blocks_per_epoch <= 0:
            return 0.0
        # Use last seen block height (or height=0 if none yet).
        h = self.last_block_height if self.last_block_height >= 0 else 0
        per_block = self._current_block_reward(h)
        return per_block * float(self.blocks_per_epoch)

    # ------------------------------------------------------------------
    # Distribution
    # ------------------------------------------------------------------

    def _choose_weighted_winner(self, pool: str) -> Optional[str]:
        """Pick a weighted random winner within a reward pool."""
        tickets = self.tickets.get(pool) or {}
        if not tickets:
            return None

        # Deterministic order for stable randomness in tests
        items = list(tickets.items())
        items.sort(key=lambda kv: kv[0])

        total_weight = sum(max(0.0, float(w)) for _, w in items)
        if total_weight <= 0:
            return None

        r = random.random() * total_weight
        cumulative = 0.0
        for account_id, weight in items:
            w = max(0.0, float(weight))
            cumulative += w
            if r <= cumulative:
                return account_id
        # Fallback – should not normally reach here
        return items[-1][0]

    def _credit(self, account_id: str, amount: float) -> None:
        if not account_id:
            return
        if amount <= 0.0:
            return
        self.balances[account_id] = self.balances.get(account_id, 0.0) + float(amount)
        if account_id == TREASURY_ACCOUNT:
            # Treasury is not in any pool by default
            return

    def get_balance(self, account_id: str) -> float:
        return float(self.balances.get(account_id, 0.0))

    # ------------------------------------------------------------------
    # Epoch + block reward interfaces used by the executor
    # ------------------------------------------------------------------

    def distribute_epoch_rewards(self, epoch: int, bootstrap_mode: bool = False) -> Dict[str, Optional[str]]:
        """
        Backwards-compat shim.

        The executor calls this at epoch boundaries to log "epoch winners".
        To avoid double-minting, this method **does not** change balances.
        Instead, it returns, for each pool, the account with the highest
        accumulated ticket weight (if any).  Callers can treat this as a
        purely informational view.
        """
        winners: Dict[str, Optional[str]] = {}
        for pool, tickets in (self.tickets or {}).items():
            if not tickets:
                winners[pool] = None
                continue
            # Pick the account with max weight as the "epoch winner"
            winner = max(tickets.items(), key=lambda kv: float(kv[1]))[0]
            winners[pool] = winner
        return winners

    def distribute_block_rewards(
        self,
        block_height: int,
        epoch: int,
        blocks_per_epoch: int,
        bootstrap_mode: bool = False,
    ) -> Dict[str, Optional[str]]:
        """
        Per-block reward distribution across all pools.

        Called by the executor for every finalized block.  Uses the current
        pool_split to carve the block reward into slices, then runs a
        weighted lottery on tickets for each pool.

        Returns a mapping of pool -> winner (or None if no winner).
        """
        self.last_block_height = max(self.last_block_height, int(block_height))
        if blocks_per_epoch:
            self.blocks_per_epoch = int(blocks_per_epoch)

        reward = self._current_block_reward(block_height)
        if reward <= 0.0:
            return {}

        # Bootstrap mode: send all rewards to treasury to avoid weird early skew.
        if bootstrap_mode:
            self.total_issued += reward
            self._credit(TREASURY_ACCOUNT, reward)
            return {pool: TREASURY_ACCOUNT for pool in self.pool_split.keys()}

        # Normal operation: split reward across pools and pick winners
        winners: Dict[str, Optional[str]] = {}
        self.total_issued += reward

        for pool, fraction in self.pool_split.items():
            pool_amount = reward * float(fraction or 0.0)
            if pool_amount <= 0.0:
                winners[pool] = None
                continue

            winner = self._choose_weighted_winner(pool)
            if winner is None:
                # No eligible tickets for this pool – route to treasury
                winner = TREASURY_ACCOUNT

            winners[pool] = winner
            self._credit(winner, pool_amount)
            self._ensure_pool(pool)
            self.pools[pool]["members"].add(winner)

        # Tickets are consumed after each block distribution
        self.clear_tickets()
        return winners


# ---------------------------------------------------------------------------
# Backwards compatible alias
# ---------------------------------------------------------------------------


class LedgerRuntime(WeCoinLedger):
    """
    Backwards-compatible alias for the previous LedgerRuntime.

    Existing code that imports LedgerRuntime will now use the same implementation
    as WeCoinLedger (block rewards, pool_split, balances, tickets, etc.).
    """
    pass
