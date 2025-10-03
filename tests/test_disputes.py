def test_create_dispute(executor):
    executor.register_user("alice")
    post = executor.create_post("alice", "Problematic post")["post_id"]
    executor.register_user("bob")
    dispute = executor.create_dispute("bob", post, "This is a dispute")
    assert dispute["ok"]
    dispute_id = dispute["dispute_id"]
    assert dispute_id in executor.state["disputes"]

def test_dispute_unregistered_user(executor):
    res = executor.create_dispute("ghost", 1, "Invalid reporter")
    assert not res["ok"]

def test_create_dispute(executor):
    executor.register_user("alice")
    post_id = executor.create_post("alice", "Problematic post")["post_id"]
    executor.register_user("bob")
    dispute = executor.create_dispute("bob", post_id, "This is a dispute")
    assert dispute["ok"]
    dispute_id = dispute["dispute_id"]
    assert dispute_id in executor.state["disputes"]

def test_dispute_unregistered_user(executor):
    res = executor.create_dispute("ghost", 1, "Invalid reporter")
    assert not res["ok"]

def test_dispute_on_nonexistent_post(executor):
    executor.register_user("alice")
    res = executor.create_dispute("alice", 999, "No post")
    assert not res["ok"]
