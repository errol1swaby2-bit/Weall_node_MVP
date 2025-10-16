import pytest
from fastapi.testclient import TestClient
from weall_node.weall_api import app

client = TestClient(app)

def test_health_and_ready():
    assert client.get("/healthz").json()["ok"]
    assert client.get("/ready").json()["ok"]

@pytest.mark.parametrize("path",["/governance/proposals","/chain/mempool"])
def test_basic_gets(path):
    resp = client.get(path)
    assert resp.status_code in (200,404)
