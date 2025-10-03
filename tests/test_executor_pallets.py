import pytest
from weall_node.executor import WeAllExecutor, GLOBAL_PARAMS

YES = "yes"
NO = "no"


@pytest.fixture
def exec():
    e = WeAllExecutor()
    # register some users with sufficient PoH
    e.register_user("alice", poh_level=3)
    e.register_user("bob", poh_level=3)
    e.register_user("carol", poh_level=3)
    e.register_user("dave", poh_level=3)
    return e


def test_treasury_allocate(exec):
    pid = exec.propose(
        "alice",
        "Fund dev pool",
        "Allocate 100 to devfund",
        pallet_reference="Treasury.allocate",
        params={"pool": "devfund", "amount": 100},
    )["id"]

    exec.vote("bob", pid, YES)
    exec.vote("carol", pid, YES)
    exec.vote("dave", pid, YES)

    assert exec.ledger.balances["devfund"] == 100


def test_treasury_mint_burn(exec):
    exec.ledger.mint("research", 50)
    assert exec.ledger.balances["research"] == 50
    exec.ledger.burn("research", 20)
    assert exec.ledger.balances["research"] == 30


def test_params_set(exec):
    pid = exec.propose(
        "alice",
        "Change quorum",
        "Set quorum to 5",
        pallet_reference="Params.set",
        params={"quorum": 5},
    )["id"]

    exec.vote("bob", pid, YES)
    exec.vote("carol", pid, YES)
    exec.vote("dave", pid, YES)

    assert GLOBAL_PARAMS["quorum"] == 5


def test_governance_set_rules(exec):
    pid = exec.propose(
        "alice",
        "Change rules",
        "Lower quorum to 2",
        pallet_reference="Governance.set_rules",
        params={"quorum": 2, "threshold": 0.5},
    )["id"]

    exec.vote("bob", pid, YES)
    exec.vote("carol", pid, YES)

    assert GLOBAL_PARAMS["quorum"] == 2


def test_governance_set_rules_insufficient_votes(exec):
    pid = exec.propose(
        "alice",
        "Change rules",
        "Lower quorum to 2",
        pallet_reference="Governance.set_rules",
        params={"quorum": 2, "threshold": 0.5},
    )["id"]

    # only 2 votes, quorum still 3 initially
    exec.vote("bob", pid, YES)
    exec.vote("carol", pid, YES)

    assert GLOBAL_PARAMS["quorum"] == 3  # unchanged
