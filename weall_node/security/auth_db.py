from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_LOCK = threading.Lock()
_DB_PATH: Optional[str] = None

DEFAULT_SESSION_TTL_SEC = 30 * 24 * 60 * 60  # 30 days


def init(db_path: str) -> None:
    global _DB_PATH
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = str(p)

    with _LOCK:
        con = _connect()
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA foreign_keys=ON;")
            con.execute("PRAGMA busy_timeout=2500;")

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id         TEXT PRIMARY KEY,
                    email           TEXT UNIQUE,
                    password_hash   TEXT NOT NULL,
                    poh_id          TEXT,
                    created_at      REAL NOT NULL,
                    last_login_at   REAL
                );
                """
            )

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id      TEXT PRIMARY KEY,
                    user_id         TEXT NOT NULL,
                    created_at      REAL NOT NULL,
                    last_seen_at    REAL NOT NULL,
                    expires_at      REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                """
            )

            con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);")

            con.commit()
        finally:
            con.close()


def _connect() -> sqlite3.Connection:
    if not _DB_PATH:
        raise RuntimeError("auth_db not initialized. Call auth_db.init(db_path) at startup.")
    con = sqlite3.connect(_DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def purge_expired_sessions(now: Optional[float] = None) -> int:
    now = time.time() if now is None else float(now)
    with _LOCK:
        con = _connect()
        try:
            cur = con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            con.commit()
            return int(cur.rowcount or 0)
        finally:
            con.close()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        con = _connect()
        try:
            row = con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            con.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    with _LOCK:
        con = _connect()
        try:
            row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            con.close()


def create_user(*, user_id: str, email: Optional[str], password_hash: str, now: float) -> Dict[str, Any]:
    with _LOCK:
        con = _connect()
        try:
            con.execute(
                """
                INSERT INTO users (user_id, email, password_hash, poh_id, created_at, last_login_at)
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (user_id, email, password_hash, now, now),
            )
            con.commit()
            row = con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return _row_to_dict(row)
        finally:
            con.close()


def update_user_login(user_id: str, now: float) -> None:
    with _LOCK:
        con = _connect()
        try:
            con.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (now, user_id))
            con.commit()
        finally:
            con.close()


def create_session(*, user_id: str, now: float, ttl_sec: int = DEFAULT_SESSION_TTL_SEC) -> str:
    sid = secrets.token_hex(16)
    expires_at = now + int(ttl_sec)

    with _LOCK:
        con = _connect()
        try:
            con.execute(
                """
                INSERT INTO sessions (session_id, user_id, created_at, last_seen_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, user_id, now, now, expires_at),
            )
            con.commit()
            return sid
        finally:
            con.close()


def get_session(session_id: str, *, touch: bool = True, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    now = time.time() if now is None else float(now)

    with _LOCK:
        con = _connect()
        try:
            row = con.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            sess = _row_to_dict(row)

            if float(sess["expires_at"]) < now:
                con.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                con.commit()
                return None

            if touch:
                con.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                    (now, session_id),
                )
                con.commit()
                sess["last_seen_at"] = now

            return sess
        finally:
            con.close()


def delete_session(session_id: str) -> None:
    if not session_id:
        return
    with _LOCK:
        con = _connect()
        try:
            con.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            con.commit()
        finally:
            con.close()
