import hashlib

def test_governance_full_cycle(executor):
    ex = executor
    ex.register_user("dev", poh_level=3)
    ex.register_user("dev2", poh_level=3)

    # use safe dummy path
    dummy_module = "weall_node/tmp_patch_module.py"
    content = "print('patched')"
    cid = ex._ipfs_add_str(content)
    checksum = hashlib.sha256(content.encode()).hexdigest()

    prop = ex.propose_code_update("dev", dummy_module, cid, checksum)
    assert prop["ok"]
    pid = prop["proposal_id"]

    ex.vote_on_proposal("dev", pid, "yes")
    ex.vote_on_proposal("dev2", pid, "yes")
    closed = ex.close_proposal(pid)
    assert closed["status"] == "passed"

    enacted = ex.try_enact_proposal("dev", pid)
    assert enacted["ok"]
