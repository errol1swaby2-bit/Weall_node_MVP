from __future__ import annotations

"""
Nonce tracking for the protobuf TX lane.

This is a minimal sqlite-backed nonce store usable without bootstrapping the
full chain/executor. It prevents replay and gives the proto mempool a
deterministic accept rule.

Safe default policy:
- next expected nonce starts at 0 for each sender
- mempool only accepts tx.nonce == expected_nonce
- after a tx is committed (in a block), call commit_nonce(sender, nonce+1)
"""

import os
import sqlite3
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class NonceStatus:
    sender: bytes
    expected_nonce: int


class ProtoNonceStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proto_nonces (
                    sender BLOB PRIMARY KEY,
                    expected_nonce INTEGER NOT NULL
                )
                """
            )

    def get_expected_nonce(self, sender: bytes) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT expected_nonce FROM proto_nonces WHERE sender=?",
                (sqlite3.Binary(sender),),
            ).fetchone()
            return int(row[0]) if row else 0

    def get_status(self, sender: bytes) -> NonceStatus:
        return NonceStatus(sender=bytes(sender), expected_nonce=self.get_expected_nonce(sender))

    def ensure_sender(self, sender: bytes) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO proto_nonces(sender, expected_nonce) VALUES (?, ?)",
                (sqlite3.Binary(sender), 0),
            )

    def commit_nonce(self, sender: bytes, new_expected_nonce: int) -> None:
        if new_expected_nonce < 0:
            raise ValueError("nonce must be >= 0")

        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO proto_nonces(sender, expected_nonce) VALUES (?, ?) "
                "ON CONFLICT(sender) DO UPDATE SET expected_nonce=excluded.expected_nonce",
                (sqlite3.Binary(sender), int(new_expected_nonce)),
            )


def default_proto_nonce_store() -> ProtoNonceStore:
    db_path = os.getenv("WEALL_PROTO_NONCE_DB", "./proto_nonces.sqlite")
    return ProtoNonceStore(db_path=db_path)


# ---------------------------------------------------------------------------
# Back-compat in-memory nonce store
# ---------------------------------------------------------------------------

class NonceStore:
    """Legacy in-memory nonce store backed by a dict.

    Older executor code expects:
        ledger["nonces"][sender_hex] -> expected_nonce (int)
    """

    def __init__(self, backing: dict):
        self._d = backing if isinstance(backing, dict) else {}

    def expected(self, sender_hex: str) -> int:
        try:
            return int(self._d.get(sender_hex, 0))
        except Exception:
            return 0

    def require(self, sender_hex: str, nonce: int) -> bool:
        return int(nonce) == int(self.expected(sender_hex))

    def commit_next(self, sender_hex: str, next_expected: int) -> None:
        self._d[str(sender_hex)] = int(next_expected)

    # ------------------------------------------------------------------
    # Back-compat with apply_proto_tx_atomic expectations
    # ------------------------------------------------------------------
    def commit(self, sender_hex: str, next_expected_nonce: int) -> None:
        """Alias for commit_next.

        The proto apply layer expects a method named `commit(sender_hex, next_expected_nonce)`.
        Older executor code used `commit_next`.
        """
        self.commit_next(sender_hex, next_expected_nonce)
