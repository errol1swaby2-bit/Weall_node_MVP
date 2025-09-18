def test_advance_epoch(executor):
    executor.register_user("alice")
    executor.register_user("bob")
    res = executor.advance_epoch(force=True)
    assert res["ok"]
    assert res["epoch"] == 1
    assert all(user in ["alice", "bob"] for user in res["winners"])

def test_epoch_not_elapsed(executor):
    executor.register_user("alice")
    res1 = executor.advance_epoch(force=True)
    res2 = executor.advance_epoch(force=False)
    assert not res2["ok"]
    assert res2["error"] == "epoch_not_elapsed"
