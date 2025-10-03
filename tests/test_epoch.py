import pytest
from weall_node.executor import WeAllExecutor

@pytest.fixture
def exec():
    e = WeAllExecutor()
    e.register_user("alice", poh_level=3)
    e.register_user("bob", poh_level=3)
    e.register_user("carol", poh_level=3)
    return e

def test_epoch_advances(exec):
    # Proposal before epoch
    pid = exec.propose("alice", "Change rules", "Set quorum=2", pallet_reference="Params.set", params={"quorum": 2})["id"]
    exec.vote("bob", pid, "YES")
    exec.vote("carol", pid, "YES")

    # Should not be enacted until epoch advances
    assert exec.state["proposals"][pid]["status"] == "open"

    # Advance epoch
    result = exec.advance_epoch()
    assert result["ok"] is True
    assert result["epoch"] == 1

    # Proposal should now be enacted
    assert exec.state["proposals"][pid]["status"] == "enacted"
    assert exec.state["proposals"][pid]["params"]["quorum"] == 2
    assert exec.state["users"]["alice"]["poh_level"] == 3
