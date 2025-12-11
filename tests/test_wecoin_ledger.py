# tests/test_wecoin_ledger.py

import pathlib
import sys
import math

import pytest

# Ensure the repo root (containing the inner weall_node package dir) is on sys.path.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weall_node.weall_runtime.ledger import (
    WeCoinLedger,
    DEFAULT_POOL_SPLIT,
    TREASURY_ACCOUNT,
)


def _almost_equal(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(a - b) <= eps


def test_first_block_all_unclaimed_goes_to_treasury():
    """
    On a fresh ledger with no tickets:

    - Every non-treasury pool's share must be redirected to the treasury account.
    - The treasury pool's share also goes to the treasury account.
    - total_issued must increase by exactly the base block reward.
    - Sum of balances must equal total_issued.
    """
    ledger = WeCoinLedger()

    # Fresh state
    assert ledger.total_issued == 0.0
    assert ledger.balances == {}

    block_height = 0
    epoch = 0
    blocks_per_epoch = 10

    base_reward = ledger._current_block_reward(block_height)
    assert base_reward > 0.0, "First block should have a positive reward"

    winners = ledger.distribute_block_rewards(
        block_height=block_height,
        epoch=epoch,
        blocks_per_epoch=blocks_per_epoch,
        bootstrap_mode=False,
    )

    # Invariants: keys match pool names
    assert set(winners.keys()) == set(DEFAULT_POOL_SPLIT.keys())

    # With no tickets, every pool should send its share to treasury
    for pool, winner in winners.items():
        assert winner == TREASURY_ACCOUNT

    # Only treasury should have a positive balance
    non_zero_accounts = {
        acct: bal for acct, bal in ledger.balances.items() if not _almost_equal(bal, 0.0)
    }
    assert set(non_zero_accounts.keys()) == {TREASURY_ACCOUNT}

    # total_issued equals the base_reward
    assert _almost_equal(ledger.total_issued, base_reward)

    # Sum of balances equals total_issued
    total_balance = sum(ledger.balances.values())
    assert _almost_equal(total_balance, ledger.total_issued)


def test_tickets_create_real_winners_not_just_treasury():
    """
    When we add a ticket for a pool, that pool should be able to pick
    a non-treasury winner and credit that account instead of treasury.
    """
    ledger = WeCoinLedger()

    # Give Alice a validator ticket
    alice = "@alice"
    ledger.add_ticket("validators", alice, weight=1.0)

    block_height = 0
    epoch = 0
    blocks_per_epoch = 10

    base_reward = ledger._current_block_reward(block_height)
    winners = ledger.distribute_block_rewards(
        block_height=block_height,
        epoch=epoch,
        blocks_per_epoch=blocks_per_epoch,
        bootstrap_mode=False,
    )

    # Validators pool should now choose Alice
    assert winners["validators"] == alice

    # Treasury still wins all pools with no tickets
    for pool, winner in winners.items():
        if pool == "validators":
            continue
        assert winner == TREASURY_ACCOUNT

    # Alice should have a positive balance
    assert ledger.balances.get(alice, 0.0) > 0.0

    # Total issued still equals base_reward
    assert math.isclose(ledger.total_issued, base_reward, rel_tol=1e-9)

    # Sum of balances equals total_issued
    total_balance = sum(ledger.balances.values())
    assert math.isclose(total_balance, ledger.total_issued, rel_tol=1e-9)


def test_epoch_end_clears_tickets():
    """
    After a block where (block_height + 1) % blocks_per_epoch == 0,
    tickets should be cleared.
    """
    ledger = WeCoinLedger()

    # Add a ticket in validators pool
    ledger.add_ticket("validators", "@alice", 1.0)
    assert ledger.tickets["validators"], "Ticket should be present before distribution"

    # Use blocks_per_epoch = 1 so every block is "end-of-epoch"
    ledger.distribute_block_rewards(
        block_height=0,
        epoch=0,
        blocks_per_epoch=1,
        bootstrap_mode=False,
    )

    # Tickets should be cleared after distribution
    for pool, tickets in ledger.tickets.items():
        assert tickets == {}, f"Tickets for pool {pool} should be cleared at epoch end"


def test_never_mints_past_max_supply():
    """
    If max_supply is small, the ledger must never mint beyond it.
    Remaining headroom caps the block reward.
    """
    # Tiny supply, big rewards => we hit cap quickly
    ledger = WeCoinLedger(
        max_supply=150.0,
        initial_block_reward=100.0,
        # Make halving interval huge so we don't halve in just a few blocks
        halving_interval_seconds=10_000_000,
    )

    # Block 0: should mint 100 (or less if something changes)
    ledger.distribute_block_rewards(
        block_height=0,
        epoch=0,
        blocks_per_epoch=10,
        bootstrap_mode=False,
    )
    assert ledger.total_issued <= ledger.max_supply

    # Block 1: should mint up to remaining headroom (50)
    ledger.distribute_block_rewards(
        block_height=1,
        epoch=0,
        blocks_per_epoch=10,
        bootstrap_mode=False,
    )
    assert ledger.total_issued <= ledger.max_supply

    # Block 2: should mint nothing (we are at cap)
    before = ledger.total_issued
    winners = ledger.distribute_block_rewards(
        block_height=2,
        epoch=0,
        blocks_per_epoch=10,
        bootstrap_mode=False,
    )

    # total_issued must not change
    assert ledger.total_issued == before

    # All winners should be None when base_reward == 0
    for pool, winner in winners.items():
        assert winner is None
