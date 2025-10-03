"""
Basic tests for WeAllExecutor.
Run with:  python tests/test_executor.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import base64, json
from weall_node.executor import WeAllExecutor
from weall_runtime.crypto_utils import verify_ed25519_sig
from pure25519 import eddsa

# -----------------------------
# Helpers
# -----------------------------
def make_keys():
    sk = eddsa.SigningKey(b"1" * 32)  # deterministic 32-byte seed
    vk = sk.get_verifying_key()
    pub_b64 = base64.b64encode(vk.to_bytes()).decode()
    return sk, pub_b64

def sign(sk, payload: dict):
    raw = json.dumps(payload, sort_keys=True).encode()
    sig = sk.sign(raw)
    return base64.b64encode(sig).decode()

# -----------------------------
# Tests
# -----------------------------
def test_transfer():
    exec = WeAllExecutor()
    sk, pub_b64 = make_keys()
    payload = {"to": "alice", "amount": 10}
    sig_b64 = sign(sk, payload)
    tx = {"type": "transfer", "user": pub_b64, "sig": sig_b64, "payload": payload}
    res = exec.execute_tx(tx)
    print("Transfer:", res)

def test_proposal_vote():
    exec = WeAllExecutor()
    sk, pub_b64 = make_keys()
    proposal = {"title": "Test", "description": "Try governance"}
    sig_b64 = sign(sk, proposal)
    tx1 = {"type": "proposal", "user": pub_b64, "sig": sig_b64, "payload": proposal}
    res1 = exec.execute_tx(tx1)
    print("Proposal:", res1)

    vote = {"proposal_id": 1, "option": "yes"}
    sig_b64 = sign(sk, vote)
    tx2 = {"type": "vote", "user": pub_b64, "sig": sig_b64, "payload": vote}
    res2 = exec.execute_tx(tx2)
    print("Vote:", res2)

def test_post():
    exec = WeAllExecutor()
    sk, pub_b64 = make_keys()
    post = {"content": "Hello world", "tags": ["intro"], "groups": [], "visibility": "public"}
    sig_b64 = sign(sk, post)
    tx = {"type": "post", "user": pub_b64, "sig": sig_b64, "payload": post}
    res = exec.execute_tx(tx)
    print("Post:", res)

def test_block():
    exec = WeAllExecutor()
    sk, pub_b64 = make_keys()
    payload = {"to": "alice", "amount": 5}
    sig_b64 = sign(sk, payload)
    tx = {"type": "transfer", "user": pub_b64, "sig": sig_b64, "payload": payload}
    block = exec.assemble_block([tx])
    print("Block:", block)

# -----------------------------
# Run all tests
# -----------------------------
if __name__ == "__main__":
    print("=== Running WeAllExecutor tests ===")
    test_transfer()
    test_proposal_vote()
    test_post()
    test_block()
