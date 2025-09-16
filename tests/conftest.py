import os
import sys
import pytest

# Add project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the main executor
from executor import WeAllExecutor

# Pytest fixture
@pytest.fixture
def executor():
    """Return a fresh WeAllExecutor instance for each test."""
    dsl_file = os.path.join(project_root, "weall_dsl_v0.5.yaml")
    return WeAllExecutor(dsl_file=dsl_file)
