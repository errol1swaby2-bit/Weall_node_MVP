"""
tests/test_messaging.py
-----------------------

Covers:
- Secure message send between registered users
- Message retrieval and decryption
- Handling of unregistered users

Includes key regeneration guard to handle fresh fixtures.
"""

from weall_node.weall_executor import generate_keypair


def test_send_and_read_message(executor):
    ex = executor

    # Ensure clean new users each run
    ex.register_user("alice", poh_level=3)
    ex.register_user("bob", poh_level=3)

    # Some persisted states may lack keys after reload; regenerate if missing
    for u in ["alice", "bob"]:
        meta = ex.state["users"].get(u, {})
        if not meta.get("public_key") or not meta.get("private_key"):
            priv, pub = generate_keypair()
            meta["private_key"], meta["public_key"] = priv, pub

    # Send encrypted message
    res = ex.send_message("alice", "bob", "Secret Message")
    assert res["ok"], f"send_message failed: {res}"

    # Bob reads and decrypts message
    inbox = ex.read_messages("bob")
    assert inbox, "Inbox empty"
    assert any("Secret" in m["text"] for m in inbox), f"Inbox contents: {inbox}"


def test_send_message_unregistered_user(executor):
    ex = executor
    # Try sending from an unregistered user
    res = ex.send_message("ghost", "bob", "Hi")
    assert not res["ok"]
    assert res["error"] == "user_not_registered"
