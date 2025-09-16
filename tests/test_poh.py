def test_user_registration(executor):
    res = executor.register_user("dave", poh_level=2)
    assert res["ok"]
    assert executor.state["users"]["dave"]["poh_level"] == 2

def test_duplicate_registration(executor):
    executor.register_user("eve")
    res = executor.register_user("eve")
    assert not res["ok"]

def test_poh_action_restriction(executor):
    executor.register_user("frank", poh_level=1)
    required_level = executor.get_required_poh("propose")
    assert required_level >= 2

def test_user_registration(executor):
    res = executor.register_user("alice", poh_level=2)
    assert res["ok"]
    assert executor.state["users"]["alice"]["poh_level"] == 2

def test_duplicate_registration(executor):
    executor.register_user("bob")
    res = executor.register_user("bob")
    assert not res["ok"]

def test_poh_action_restriction(executor):
    executor = type(executor)(dsl_file=executor.dsl_file, poh_requirements={"propose": 2})
    executor.register_user("frank", poh_level=1)
    required_level = executor.get_required_poh("propose")
    assert required_level >= 2

def test_set_user_eligible(executor):
    executor.register_user("george")
    executor.set_user_eligible("george", False)
    assert not executor.ledger.eligible["george"]
