def test_send_and_read_message(executor):
    executor.register_user("alice")
    executor.register_user("bob")
    res = executor.send_message("alice", "bob", "Secret Message")
    assert res["ok"]

    messages = executor.read_messages("bob")
    assert len(messages) == 1
    assert messages[0]["text"] == "Secret Message"

def test_send_message_unregistered_user(executor):
    executor.register_user("alice")
    res = executor.send_message("alice", "ghost", "Hello")
    assert not res["ok"]

def test_send_and_read_message(executor):
    executor.register_user("alice")
    executor.register_user("bob")
    res = executor.send_message("alice", "bob", "Secret Message")
    assert res["ok"]
    messages = executor.read_messages("bob")
    assert len(messages) == 1
    assert messages[0]["text"] == "Secret Message"

def test_send_message_unregistered_user(executor):
    executor.register_user("alice")
    res = executor.send_message("alice", "ghost", "Hello")
    assert not res["ok"]
