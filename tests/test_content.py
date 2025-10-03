import pytest

@pytest.mark.parametrize("user_id", ["alice", "bob"])
def test_create_post(executor, user_id):
    executor.register_user(user_id)
    result = executor.create_post(user_id, "Hello World!", tags=["test"])
    assert result["ok"]
    assert result["post_id"] in executor.state["posts"]

def test_create_comment(executor):
    executor.register_user("alice")
    post = executor.create_post("alice", "Post for comment")["post_id"]
    executor.register_user("bob")
    comment = executor.create_comment("bob", post, "Nice post!")["comment_id"]
    assert comment in executor.state["comments"]
    assert comment in executor.state["posts"][post]["comments"]

def test_post_without_user(executor):
    res = executor.create_post("ghost", "No user")
    assert not res["ok"]

@pytest.mark.parametrize("user_id", ["alice", "bob"])
def test_create_post(executor, user_id):
    executor.register_user(user_id)
    result = executor.create_post(user_id, "Hello World!", tags=["test"])
    assert result["ok"]
    assert result["post_id"] in executor.state["posts"]

def test_create_comment(executor):
    executor.register_user("alice")
    post_id = executor.create_post("alice", "Post for comment")["post_id"]
    executor.register_user("bob")
    comment = executor.create_comment("bob", post_id, "Nice post!")["comment_id"]
    assert comment in executor.state["comments"]
    assert comment in executor.state["posts"][post_id]["comments"]

def test_post_without_user(executor):
    res = executor.create_post("ghost", "No user")
    assert not res["ok"]
