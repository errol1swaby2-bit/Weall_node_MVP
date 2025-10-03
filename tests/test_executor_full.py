import pytest
import time
from weall_node.executor import WeAllExecutor, GLOBAL_PARAMS


@pytest.fixture
def exec():
    e = WeAllExecutor()
    e.register_user("alice", poh_level=3)
    e.register_user("bob", poh_level=3)
    e.register_user("carol", poh_level=3)
    return e


# -----------------------------
# Epoch advancement
# -----------------------------
def test_epoch_advances(exec):
    start = exec.current_epoch
    res = exec.advance_epoch()
    assert res["ok"]
    assert exec.current_epoch == start + 1
    assert "winners" in res


# -----------------------------
# Governance / Proposals
# -----------------------------
def test_governance_set_params(exec):
    pid = exec.propose(
        "alice",
        "Lower quorum",
        "Set quorum to 2",
        pallet_reference="Params.set",
        params={"quorum": 2},
    )["id"]

    exec.vote("bob", pid, "YES")
    exec.vote("carol", pid, "YES")

    assert GLOBAL_PARAMS["quorum"] == 2
    assert exec.state["proposals"][pid]["status"] == "enacted"


# -----------------------------
# Disputes
# -----------------------------
def test_dispute_and_juror_votes(exec):
    # Alice posts content
    post = exec.create_post("alice", "Bad post")["post_id"]

    # Bob reports it
    dispute_id = exec.create_dispute("bob", "post", post, "Inappropriate")["dispute_id"]

    # Jurors vote
    exec.juror_vote("bob", dispute_id, "remove")
    exec.juror_vote("carol", dispute_id, "remove")

    status = exec.state["disputes"][dispute_id]["status"]
    assert status.startswith("resolved")
    assert post not in exec.state["posts"]  # content removed
    assert exec.state["users"]["alice"]["reputation"] < 0 or \
           exec.state["users"]["alice"]["reputation"] <= 0


# -----------------------------
# Reputation adjustments
# -----------------------------
def test_reputation_changes(exec):
    start_rep = exec.state["users"]["bob"]["reputation"]

    exec.grant_reputation("bob", 5)
    assert exec.state["users"]["bob"]["reputation"] == start_rep + 5

    exec.slash_reputation("bob", 2)
    assert exec.state["users"]["bob"]["reputation"] == start_rep + 3


# -----------------------------
# Messaging
# -----------------------------
def test_plain_message(exec):
    res = exec.send_message("alice", "bob", "Hello Bob")
    assert res["ok"]
    assert exec.state["messages"]["bob"][0]["content"] == "Hello Bob"
    assert not exec.state["messages"]["bob"][0]["encrypted"]


def test_encrypted_message(exec):
    key = b"supersecretkey"
    res = exec.send_message("alice", "bob", "Secret!", encrypt=True, key=key)
    assert res["ok"]
    msg = exec.state["messages"]["bob"][1]
    assert msg["encrypted"]
    assert isinstance(msg["content"], str)  # base64 string
