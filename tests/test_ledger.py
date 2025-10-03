import pytest

def test_account_creation(executor):
    user_id = "alice"
    executor.register_user(user_id)
    assert executor.ledger.balance(user_id) == 0.0

def test_deposit_and_balance(executor):
    user_id = "bob"
    executor.register_user(user_id)
    executor.ledger.deposit(user_id, 50)
    assert executor.ledger.balance(user_id) == 50

def test_transfer(executor):
    executor.register_user("alice")
    executor.register_user("bob")
    executor.ledger.deposit("alice", 100)
    assert executor.ledger.transfer("alice", "bob", 40) is True
    assert executor.ledger.balance("alice") == 60
    assert executor.ledger.balance("bob") == 40

def test_pool_eligibility(executor):
    executor.register_user("charlie")
    executor.ledger.set_eligible("charlie", False)
    executor.ledger.add_to_pool("creators", "charlie")
    assert "charlie" not in executor.ledger.pools["creators"]


def test_account_creation(executor):
    executor.register_user("alice")
    assert executor.ledger.balance("alice") == 0

def test_deposit_and_balance(executor):
    executor.register_user("bob")
    executor.ledger.deposit("bob", 50)
    assert executor.ledger.balance("bob") == 50

def test_transfer(executor):
    executor.register_user("alice")
    executor.register_user("bob")
    executor.ledger.deposit("alice", 100)
    success = executor.ledger.transfer("alice", "bob", 40)
    assert success
    assert executor.ledger.balance("alice") == 60
    assert executor.ledger.balance("bob") == 40

def test_pool_eligibility(executor):
    executor.register_user("charlie")
    executor.ledger.set_eligible("charlie", False)
    executor.ledger.add_to_pool("creators", "charlie")
    assert "charlie" not in executor.ledger.pools["creators"]

def test_distribute_epoch_rewards(executor):
    executor.register_user("dave")
    executor.register_user("eve")
    executor.ledger.add_to_pool("creators", "dave")
    executor.ledger.add_to_pool("creators", "eve")
    winners = executor.ledger.distribute_epoch_rewards(seed=1)
    assert all(user in ["dave", "eve"] for user in winners)
    for user, reward in winners.items():
        assert reward == 10
