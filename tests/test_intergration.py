import pytest

# ---------------------------
# Integration Tests for WeAllExecutor
# ---------------------------

def test_multiple_users_posts_comments(executor):
    # Register users
    users = ["alice", "bob", "carol"]
    for user in users:
        executor.register_user(user)

    # Alice creates a post
    post_res = executor.create_post("alice", "Alice's first post", tags=["intro"])
    post_id = post_res["post_id"]
    assert post_res["ok"]
    
    # Bob and Carol comment
    comment_bob = executor.create_comment("bob", post_id, "Nice post, Alice!")["comment_id"]
    comment_carol = executor.create_comment("carol", post_id, "Welcome!")["comment_id"]

    # Verify comments attached to post
    post = executor.state["posts"][post_id]
    assert comment_bob in post["comments"]
    assert comment_carol in post["comments"]

def test_disputes_and_resolution(executor):
    # Register users
    executor.register_user("dave")
    executor.register_user("eve")
    
    # Dave creates a post
    post_id = executor.create_post("dave", "Controversial post")["post_id"]

    # Eve disputes the post
    dispute = executor.create_dispute("eve", post_id, "Inappropriate content")
    dispute_id = dispute["dispute_id"]
    assert dispute["ok"]
    
    # Check dispute state
    stored_dispute = executor.state["disputes"][dispute_id]
    assert stored_dispute["reporter"] == "eve"
    assert stored_dispute["post_id"] == post_id
    assert stored_dispute["status"] == "open"

def test_messaging_between_users(executor):
    # Register users
    executor.register_user("frank")
    executor.register_user("grace")

    # Frank sends message to Grace
    msg_res = executor.send_message("frank", "grace", "Hello Grace!")
    assert msg_res["ok"]

    # Grace reads message
    messages = executor.read_messages("grace")
    assert len(messages) == 1
    assert messages[0]["text"] == "Hello Grace!"
    assert messages[0]["from"] == "frank"

def test_epoch_rewards_multiple_users(executor):
    # Register users
    users = ["alice", "bob", "carol"]
    for u in users:
        executor.register_user(u)

    # All users create posts to join "creators" pool
    for u in users:
        executor.create_post(u, f"{u}'s post")

    # Advance epoch forcefully
    epoch_res = executor.advance_epoch(force=True)
    assert epoch_res["ok"]
    winners = epoch_res["winners"]

    # Each winner received reward
    for winner, reward in winners.items():
        assert winner in users
        assert reward == 10
        assert executor.ledger.balance(winner) >= 10

def test_poh_restrictions_on_actions(executor):
    # Register users with levels
    executor.register_user("hank", poh_level=1)
    executor.register_user("irene", poh_level=3)

    # Default PoH requirements: propose=2, vote=1
    propose_level = executor.get_required_poh("propose")
    vote_level = executor.get_required_poh("vote")
    assert propose_level >= 2
    assert vote_level >= 1

    # Low-level user cannot propose
    assert executor.state["users"]["hank"]["poh_level"] < propose_level

    # High-level user can propose
    assert executor.state["users"]["irene"]["poh_level"] >= propose_level

def test_combined_workflow(executor):
    # Register multiple users
    users = ["alice", "bob", "carol", "dave"]
    for u in users:
        executor.register_user(u)

    # Users post
    post_ids = []
    for u in users:
        post_ids.append(executor.create_post(u, f"{u}'s post")["post_id"])

    # Commenting
    executor.create_comment("alice", post_ids[1], "Nice post Bob!")
    executor.create_comment("bob", post_ids[0], "Thanks Alice!")

    # Disputes
    dispute_res = executor.create_dispute("carol", post_ids[3], "Offensive content")
    assert dispute_res["ok"]

    # Messaging
    executor.send_message("dave", "alice", "Check your post")
    messages = executor.read_messages("alice")
    assert any(m["from"] == "dave" for m in messages)

    # Advance epoch
    epoch_res = executor.advance_epoch(force=True)
    assert epoch_res["ok"]
