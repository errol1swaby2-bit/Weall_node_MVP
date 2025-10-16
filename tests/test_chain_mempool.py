from weall_node.weall_executor import WeAllExecutor

def test_chain_mempool_and_finalize(executor: WeAllExecutor):
    ex = executor
    ex.register_user("alice", poh_level=3)
    ex.record_to_mempool({"event": "sample_event", "data": 123})

    mempool = ex.chain.get_mempool()
    # new chain returns plain dicts or objects — check string match
    assert any("sample_event" in str(m) for m in mempool)

    # validator selection can fall back to default "x"
    selected = ex.select_validator(seed=1)
    assert selected in ("alice", "x")

    # finalize block replaces old validate_mempool()
    res = ex.finalize_block("alice")
    assert isinstance(res, dict)
    assert res.get("ok", True)
