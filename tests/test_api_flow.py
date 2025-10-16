import pytest
from httpx import AsyncClient
from weall_node.weall_api import app, EXEC

@pytest.mark.asyncio
async def test_full_api_flow():
    EXEC.reset_state()

    async with AsyncClient(app=app, base_url="http://test") as client:
        # --- Proof-of-Humanity Tier 1 ---
        r1 = await client.post("/poh/request-tier1",
                               json={"user": "alice", "email": "alice@test.com"})
        assert r1.status_code == 200
        j1 = r1.json()
        assert "ok" in j1 or "message" in j1

        # --- Tier 2 evidence upload ---
        r2 = await client.post("/poh/tier2",
                               json={"user": "alice", "evidence": "ipfs://proof"})
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2.get("ok", True)

        # --- Tier 3 request (new endpoint) ---
        r3 = await client.post("/poh/tier3/request",
                               json={"user_id": "alice"})
        assert r3.status_code == 200
        j3 = r3.json()
        assert j3.get("ok", True)
        assert j3.get("phase") == "A_pending"

        # --- Basic post + comment roundtrip ---
        post = await client.post("/post",
                                 json={"user_id": "alice",
                                       "content": "Hello world"})
        assert post.status_code == 200
        pid = post.json()["post_id"]
        comment = await client.post("/comment",
                                    json={"user_id": "alice",
                                          "post_id": pid,
                                          "content": "self-reply"})
        assert comment.status_code == 200
