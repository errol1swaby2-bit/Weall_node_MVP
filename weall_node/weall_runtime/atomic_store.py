from __future__ import annotations

"""
Atomic persistence helpers (hardened).

Adds:
- Atomic write with directory fsync
- Rolling backups (.bak1, .bak2, ...) to survive partial writes/corruption
- Load fallback: primary -> bak1 -> bak2 -> ...
- Optional write-ahead journal (.journal) so we can detect incomplete saves

This remains JSON snapshot storage (not log-structured), but the backup +
journal behavior gives you "crash survivability" similar to a lightweight WAL.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union


JsonDict = Dict[str, Any]
PathLike = Union[str, Path]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _fsync_dir(dir_path: Path) -> None:
    try:
        fd = os.open(str(dir_path), os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def _json_dumps(obj: JsonDict) -> bytes:
    # canonical-ish JSON for stable hashing/debug
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    _ensure_dir(path.parent)

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(str(tmp_path), str(path))
        _fsync_dir(path.parent)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def read_json(path: Path) -> Optional[JsonDict]:
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _rotate_backups(path: Path, keep: int) -> None:
    if keep <= 0:
        return

    # move .bak(N-1) -> .bakN
    for i in range(keep, 1, -1):
        src = path.with_suffix(path.suffix + f".bak{i-1}")
        dst = path.with_suffix(path.suffix + f".bak{i}")
        if src.exists():
            try:
                os.replace(str(src), str(dst))
            except Exception:
                pass

    # move primary -> .bak1
    if path.exists():
        bak1 = path.with_suffix(path.suffix + ".bak1")
        try:
            os.replace(str(path), str(bak1))
        except Exception:
            pass


@dataclass
class AtomicLedgerStore:
    data_dir: Path
    filename: str = "ledger_state.json"
    keep_backups: int = 2

    def __init__(
        self,
        data_dir: Optional[PathLike] = None,
        *,
        root_dir: Optional[PathLike] = None,
        base_dir: Optional[PathLike] = None,
        filename: str = "ledger_state.json",
        keep_backups: int = 2,
        **_ignored: Any,
    ):
        chosen = data_dir or root_dir or base_dir or "."
        self.data_dir = Path(chosen)
        self.filename = filename
        self.keep_backups = int(keep_backups)

    @property
    def path(self) -> Path:
        return self.data_dir / self.filename

    @property
    def journal_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".journal")

    def exists(self) -> bool:
        return self.path.exists()

    # ---------------------------
    # Load: primary -> backups
    # ---------------------------
    def load(self) -> Optional[JsonDict]:
        # If a journal exists, last save may have crashed mid-flight.
        # We still try primary; if it fails, we fall back to backups.
        paths = [self.path]
        for i in range(1, max(1, self.keep_backups) + 1):
            paths.append(self.path.with_suffix(self.path.suffix + f".bak{i}"))

        for p in paths:
            obj = read_json(p)
            if isinstance(obj, dict):
                return obj

        return None

    # ---------------------------
    # Save: journal + rotate backups + atomic write + clear journal
    # ---------------------------
    def save(self, state: JsonDict) -> None:
        _ensure_dir(self.data_dir)

        data = _json_dumps(state)

        # Write a journal marker first (best-effort).
        try:
            atomic_write_bytes(self.journal_path, b"1")
        except Exception:
            pass

        # Rotate backups before writing new primary.
        _rotate_backups(self.path, keep=self.keep_backups)

        # Write new primary atomically.
        atomic_write_bytes(self.path, data)

        # Clear journal after successful commit.
        try:
            if self.journal_path.exists():
                self.journal_path.unlink()
        except Exception:
            pass

    # Legacy aliases
    def load_snapshot(self) -> Optional[JsonDict]:
        return self.load()

    def save_snapshot(self, state: JsonDict) -> None:
        self.save(state)

    def compact(self, state: JsonDict) -> None:
        # For snapshot stores, save() is effectively compaction.
        self.save(state)


# Back-compat alias
AtomicStore = AtomicLedgerStore
