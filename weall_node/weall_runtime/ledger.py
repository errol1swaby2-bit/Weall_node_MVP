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
recorded during that block / epoch.

Production invariants:

- `total_issued` always equals the sum of all WeCoin actually credited.
- No reward share is ever "lost": if a non-treasury pool has no winner,
  its share is redirected to the treasury account.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Monetary policy constants
# ---------------------------------------------------------------------------

MAX_SUPPLY: float = 21_000_000.0  # total WeCoin (WCN) that can ever exist
INITIAL_BLOCK_REWARD: float = 100.0  # WCN per block at height 0
BLOCK_INTERVAL_SECONDS: int = 600

# Time between halvings (~2 years) and equivalent blocks-per-halving.
HALVING_INTERVAL_SECONDS: int = 2 * 365 * 24 * 60 * 60  # 2 years
BLOCKS_PER_HALVING: int = max(1, HALVING_INTERVAL_SECONDS // BLOCK_INTERVAL_SECONDS)

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


TREASURY_ACCOUNT = "@weall_treasury"


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
    block_interval_seconds: int = BLOCK_INTERVAL_SECONDS
    halving_interval_seconds: int = HALVING_INTERVAL_SECONDS

    # Reward pools + balances
    balances: Dict[str, float] = field(default_factory=dict)
    pool_split: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_POOL_SPLIT)
    )
    pools: Dict[str, Dict[str, set]] = field(
        default_factory=lambda: {
            name: {"members": set()} for name in DEFAULT_POOL_SPLIT.keys()
        }
    )
    tickets: Dict[str, Dict[str, float]] = field(
        default_factory=lambda: {name: {} for name in DEFAULT_POOL_SPLIT.keys()}
    )

    total_issued: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_pool(self, pool: str) -> None:
        if pool not in self.pools:
            self.pools[pool] = {"members": set()}
        if pool not in self.tickets:
            self.tickets[pool] = {}

    def set_pool_split(self, new_split: Dict[str, float]) -> None:
        """
        Update the reward pool split.

        The executor or genesis wiring can call this to override the default
        20/20/20/20/20 split. Values are normalized to sum to 1.0.
        """
        self.pool_split = _normalize_pool_split(new_split)

        # Ensure pools/tickets dictionaries have entries for all pools
        for name in self.pool_split.keys():
            self._ensure_pool(name)

    # ------------------------------------------------------------------
    # Ticket management
    # ------------------------------------------------------------------

    def add_member(self, pool: str, account_id: str) -> None:
        """
        Record that an account is a member of a given rewards pool.

        This is mostly a convenience method; the actual lottery uses tickets,
        but we keep membership sets handy for potential future logic.
        """
        if not account_id:
            return
        self._ensure_pool(pool)
        self.pools[pool]["members"].add(account_id)

    def add_ticket(self, pool: str, account_id: str, weight: float) -> None:
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

        Halvings occur every `blocks_per_halving` blocks. After N halvings,
        the reward is INITIAL_BLOCK_REWARD / 2**N.

        We also clamp the reward so that total_issued never exceeds max_supply.
        """
        # Already at or above max supply: no more emission.
        if self.total_issued >= self.max_supply:
            return 0.0

        blocks_per_halving = max(
            1, self.halving_interval_seconds // self.block_interval_seconds
        )

        if block_height < 0:
            block_height = 0

        halving_count = block_height // blocks_per_halving
        base_reward = self.initial_block_reward / float(2**halving_count)

        # No negative/zero rewards.
        if base_reward <= 0:
            return 0.0

        # Do not exceed remaining headroom to max_supply.
        remaining = self.max_supply - self.total_issued
        if remaining <= 0:
            return 0.0

        return float(min(base_reward, remaining))

    def _lottery_winner(
        self, pool: str, tickets: Dict[str, float]
    ) -> Optional[str]:
        """
        Deterministically pick a lottery winner from the tickets in a pool.

        NOTE: For now, we just pick the highest-weight ticket. In the future,
        we may wire this to a deterministic VRF or on-chain randomness beacon.
        """
        if not tickets:
            return None
        # Pick the account with the highest ticket weight
        best_account, best_weight = None, -1.0
        for account_id, weight in tickets.items():
            try:
                w = float(weight)
            except Exception:
                continue
            if w > best_weight:
                best_account, best_weight = account_id, w
        return best_account

    def _weighted_random_choice(
        self, items: List[Tuple[str, float]]
    ) -> Optional[str]:
        """
        Placeholder for a future VRF-based lottery.

        Right now, we do not call this method; _lottery_winner() simply picks
        the highest-weight ticket. This exists to make it easy to switch to
        a more principled lottery mechanism later.
        """
        if not items:
            return None
        total = 0.0
        for _, w in items:
            try:
                total += float(w)
            except Exception:
                continue
        if total <= 0:
            return None

        # Very simple deterministic choice based on rounding cumulative weights.
        # This is not cryptographically secure; it is a placeholder.
        r = total / 2.0
        cumulative = 0.0
        for account_id, w in items:
            try:
                fw = float(w)
            except Exception:
                continue
            cumulative += fw
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

    def distribute_epoch_rewards(
        self, epoch: int, bootstrap_mode: bool = False
    ) -> Dict[str, Optional[str]]:
        """
        Backwards-compat shim.

        The executor calls this at epoch boundaries to log "epoch winners".
        To avoid double-minting, this method **does not** change balances.
        Instead, it returns, for each pool, the account with the highest
        ticket weight during that epoch.

        In bootstrap_mode, it may return None for certain pools; the executor
        can use that as a hint to avoid over-rewarding a single validator or
        small cartel while the network is small.
        """
        results: Dict[str, Optional[str]] = {}
        for pool, split in self.pool_split.items():
            tickets = self.tickets.get(pool, {}) or {}
            if not tickets:
                results[pool] = None
                continue
            # In bootstrap mode, we *could* down-weight "too dominant" accounts;
            # for now we simply pick the top ticket as in normal mode.
            winner = self._lottery_winner(pool, tickets)
            results[pool] = winner
        # Note: we do **not** clear tickets or mint here; that is the job of
        # distribute_block_rewards.
        return results

    def distribute_block_rewards(
        self,
        block_height: int,
        epoch: int,
        blocks_per_epoch: int,
        bootstrap_mode: bool = False,
    ) -> Dict[str, Optional[str]]:
        """
        Distribute WeCoin for a **single committed block**.

        Called by the executor on each committed block with the current
        block_height, epoch index, and blocks_per_epoch.

        For each reward pool:
        - Compute the per-pool block reward = base_block_reward * pool_split[pool]
        - Select a pool winner via tickets (if any)
        - Credit the winner's balance
        - If a non-treasury pool has no winner, its share is redirected to the
          treasury account instead of being burned or lost.
        - Reset tickets at the end of an epoch (so that the next epoch starts fresh)

        Invariants:
        - The total amount credited across all pools equals base_block_reward.
        - total_issued is increased by exactly base_block_reward.
        """
        winners: Dict[str, Optional[str]] = {}

        base_reward = self._current_block_reward(block_height)
        if base_reward <= 0.0:
            # No more emission – just clear tickets at epoch boundaries
            if (block_height + 1) % max(1, blocks_per_epoch) == 0:
                self.clear_tickets()
            for pool in self.pool_split.keys():
                winners[pool] = None
            return winners

        # Per-pool rewards (shares add up to base_reward by construction)
        for pool, fraction in self.pool_split.items():
            amount = base_reward * float(fraction)

            # Treasury pool is special: it always credits the treasury account
            if pool == "treasury":
                self._credit(TREASURY_ACCOUNT, amount)
                winners[pool] = TREASURY_ACCOUNT
                continue

            tickets = self.tickets.get(pool, {}) or {}
            winner = None
            if tickets:
                winner = self._lottery_winner(pool, tickets)

            if not winner:
                # No valid winner for this pool → redirect share to treasury
                self._credit(TREASURY_ACCOUNT, amount)
                winners[pool] = TREASURY_ACCOUNT
            else:
                self._credit(winner, amount)
                winners[pool] = winner

        # Track issuance: all pool shares (including redirected ones) sum to base_reward
        self.total_issued += base_reward

        # End-of-epoch cleanup: reset tickets so next epoch starts fresh
        if (block_height + 1) % max(1, blocks_per_epoch) == 0:
            self.clear_tickets()

        return winners


# ---------------------------------------------------------------------------
# Backwards-compat exports
# ---------------------------------------------------------------------------

# These names are imported by older modules (api/chain.py, etc.). We keep
# them as aliases so those modules continue to work without modification.
INITIAL_EPOCH_REWARD: float = INITIAL_BLOCK_REWARD
HALVING_INTERVAL: int = HALVING_INTERVAL_SECONDS


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
