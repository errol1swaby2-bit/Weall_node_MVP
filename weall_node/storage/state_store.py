from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class JSONStateStore:
    """
    Minimal JSON-based state store for the local node.

    Used as the backing store for executor.ledger.
    Safe for single-node / MVP usage.
    """

    def __init__(self, path: str = "weall_state.json") -> None:
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                # Corrupted file; start clean but do not delete automatically.
                return {}
        return {}

    def save(self, state: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
