import os

def test_save_and_reload(executor):
    executor.register_user("x", poh_level=3)
    executor.save_state()
    path = os.path.join(executor.repo_root, "executor_state.json")
    assert os.path.exists(path)
