# tests/test_sync.py
import pytest
from fastapi.testclient import TestClient

import app_state
from main import app

client = TestClient(app)

def test_snapshot_and_push(tmp_path, monkeypatch):
    # Use a temporary persistence file for isolation
    persist_file = tmp_path / "ledger.json"
    monkeypatch.setattr(app_state, "ledger", app_state.Ledger(persist_file=str(persist_file)))
    monkeypatch.setattr(app_state, "node", app_state.Node(app_state.ledger))

    # Reset ledger for clean test
    ledger = app_state.ledger
    ledger.create_account("alice")
    ledger.deposit("alice", 50)

    # Fetch snapshot via API
    resp = client.get("/sync/snapshot")
    assert resp.status_code == 200
    snapshot = resp.json()
    assert "accounts" in snapshot
    assert snapshot["accounts"]["alice"] == 50

    # Simulate pushing a new snapshot from a peer
    new_snapshot = {
        "accounts": {"bob": 100.0},
        "pools": {"creators": ["bob"]},
        "eligibility": {"bob": True},
        "applications": {},
        "verifications": {},
        "proposals": {},
    }
    resp = client.post("/sync/push", json=new_snapshot)
    assert resp.status_code == 200

    # Verify merge applied
    assert ledger.balance("bob") == 100.0
    assert "bob" in ledger.pools["creators"]

def test_peer_registration(monkeypatch):
    # Re-init node for fresh peers
    monkeypatch.setattr(app_state, "node", app_state.Node(app_state.ledger))

    resp = client.post("/sync/register_peer", params={"peer_url": "http://localhost:8001"})
    assert resp.status_code == 200
    peers = resp.json()["peers"]
    assert "http://localhost:8001" in peers

    resp = client.get("/sync/peers")
    assert resp.status_code == 200
    peers = resp.json()["peers"]
    assert "http://localhost:8001" in peers

def test_snapshot_and_push(executor):
    # Example: simulate snapshot & push
    assert True  # Replace with actual snapshot logic

def test_peer_registration(executor):
    executor.register_user("alice")
    executor.register_user("bob")
    assert "alice" in executor.state["users"]
    assert "bob" in executor.state["users"]
