import os
import shutil
import pytest
import pathlib
from weall_node.weall_executor import WeAllExecutor

@pytest.fixture(scope="function")
def executor(tmp_path):
    """Fresh executor per test, isolated repo dir"""
    repo = tmp_path / "repo"
    repo.mkdir()
    os.chdir(repo)
    # Ensure old files are gone
    for f in ["executor_state.json", "chain.json", "ledger.json"]:
        if os.path.exists(f):
            os.remove(f)
    ex = WeAllExecutor(dsl_file="weall_dsl_v0.5.yaml", poh_requirements={"propose":3,"vote":2,"dispute":3})
    ex.config["require_ipfs"] = False
    ex._ipfs_add_str = lambda c: f"mock-{hash(c)%999999}"
    ex._ipfs_cat = lambda h: b"# mock\nprint('patched')\n"
    yield ex
    ex.stop()
