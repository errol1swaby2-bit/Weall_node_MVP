"""
WeAll Node Package
==================
Exports the main runtime and governance interfaces with safe fallbacks.

Primary imports you can rely on:
    from weall_node import WeAllExecutor, POH_REQUIREMENTS, DEFAULT_CONFIG, ProposalType
"""

__version__ = "0.7.0"

from pathlib import Path

# --- Optional: load YAML config if present ---
DEFAULT_CONFIG = {}
_CONFIG_PATH = Path(__file__).parent / "weall_config.yaml"
if _CONFIG_PATH.exists():
    try:
        import yaml  # keep optional; if missing, we just skip
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            DEFAULT_CONFIG = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[WeAll] Warning: failed to load weall_config.yaml: {e}")

# --- Prefer the modern executor (weall_executor) with PoH gates ---
WeAllExecutor = None
POH_REQUIREMENTS = {}

try:
    from .weall_executor import WeAllExecutor as _ExecModern, POH_REQUIREMENTS as _POH
    WeAllExecutor = _ExecModern
    POH_REQUIREMENTS = _POH
except Exception as e_modern:
    # Fallback: legacy executor path (used by some tests)
    try:
        from .executor import WeAllExecutor as _ExecLegacy
        WeAllExecutor = _ExecLegacy
        # Provide a minimal POH_REQUIREMENTS if legacy lacks it
        POH_REQUIREMENTS = {
            "register": 0,
            "send_message": 1,
            "add_friend": 1,
            "view_content": 1,
            "report": 1,
            "post": 2,
            "comment": 2,
            "resolve_dispute": 3,
            "govern": 3,
            "submit_proposal": 3,
            "vote_proposal": 3,
            "execute_proposal": 3,
            "produce_block": 3,
            "treasury_access": 3,
            "epoch_control": 3,
            "node_operator": 3,
            "storage_provider": 3,
        }
        print("[WeAll] Using legacy WeAllExecutor fallback (weall_node/executor.py).")
    except Exception as e_legacy:
        raise ImportError(
            f"Unable to import any WeAllExecutor. "
            f"Modern error: {e_modern} | Legacy error: {e_legacy}"
        )

# --- Governance exports (optional) ---
ProposalType = None
try:
    # prefer your top-level governance module if present
    from .governance import ProposalType as _ProposalType  # type: ignore
    ProposalType = _ProposalType
except Exception:
    # if you only have app_state governance, expose a minimal enum-like shim
    class _PT:
        TEXT = "text"
        PARAM_CHANGE = "param_change"
        TREASURY_ALLOC = "treasury_alloc"
        CODE_UPGRADE = "code_upgrade"
    ProposalType = _PT  # type: ignore

__all__ = [
    "WeAllExecutor",
    "POH_REQUIREMENTS",
    "DEFAULT_CONFIG",
    "ProposalType",
    "__version__",
]
