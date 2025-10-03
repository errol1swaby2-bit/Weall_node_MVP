import os
import pytest
from weall_node.executor import WeAllExecutor

@pytest.fixture
def executor():
    """Return a fresh WeAllExecutor instance for each test."""
    # DSL file is optional, only pass if needed
    dsl_file = os.path.join(os.path.dirname(__file__), "../../weall_dsl_v0.5.yaml")
    return WeAllExecutor(dsl_file=dsl_file)
