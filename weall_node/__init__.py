"""
WeAll Node package initializer (v1.1)
-------------------------------------
Provides the unified entry point for executor and app state loading.
"""

from importlib import import_module

# Prefer legacy path (executor.py), but gracefully fall back to weall_executor.py
try:
    from .executor import WeAllExecutor  # wrapper or legacy filename
except Exception:
    from .weall_executor import WeAllExecutor  # new filename

# Optional app_state import for shared executor (non-fatal if missing)
try:
    app_state = import_module("weall_node.app_state")
except ModuleNotFoundError:
    app_state = None

__all__ = ["WeAllExecutor", "app_state"]
