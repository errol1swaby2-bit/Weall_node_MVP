def test_deterministic_validator_selection(executor):
    ex = executor
    ex.register_user("v1",poh_level=3)
    ex.register_user("v2",poh_level=3)
    first = ex.select_validator(seed=42)
    second = ex.select_validator(seed=42)
    assert first == second
