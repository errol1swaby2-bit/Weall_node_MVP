#!/usr/bin/env python3
"""
SQLiteStore — Persistent storage backend for WeAll node.
---------------------------------------------------------
- Provides tables for ledger, chain, governance, and PoH events.
- Designed for durability and atomic writes.
- Used only when config.persistence.driver == "sqlite".
"""

import sqlite3
import json
import time
import os
from typing import Dict, Any, List


class SQLiteStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True) if "/" in db_path else None
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # -----------------------------------------------------
    # Core schema
    # -----------------------------------------------------
    def _init_schema(self):
        cur = self.conn.cursor()

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                balance REAL NOT NULL DEFAULT 0,
                ts INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS chain_blocks (
                height INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER,
                prev_hash TEXT,
                hash TEXT,
                txs TEXT
            );

            CREATE TABLE IF NOT EXISTS governance_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator TEXT,
                title TEXT,
                description TEXT,
                params TEXT,
                status TEXT,
                votes TEXT,
                ts INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS poh_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                tier INTEGER,
                metadata TEXT,
                ts INTEGER DEFAULT (strftime('%s','now'))
            );
            """
        )
        self.conn.commit()

    # -----------------------------------------------------
    # Ledger
    # -----------------------------------------------------
    def get_balance(self, user: str) -> float:
        cur = self.conn.execute("SELECT balance FROM ledger WHERE user=?", (user,))
        row = cur.fetchone()
        return float(row["balance"]) if row else 0.0

    def update_balance(self, user: str, delta: float):
        cur = self.conn.cursor()
        cur.execute("SELECT balance FROM ledger WHERE user=?", (user,))
        row = cur.fetchone()
        if row:
            new_bal = float(row["balance"]) + delta
            cur.execute("UPDATE ledger SET balance=? WHERE user=?", (new_bal, user))
        else:
            cur.execute("INSERT INTO ledger (user,balance) VALUES (?,?)", (user, delta))
        self.conn.commit()

    # -----------------------------------------------------
    # Chain
    # -----------------------------------------------------
    def add_block(self, prev_hash: str, block_hash: str, txs: List[dict]):
        self.conn.execute(
            "INSERT INTO chain_blocks (ts, prev_hash, hash, txs) VALUES (?,?,?,?)",
            (int(time.time()), prev_hash, block_hash, json.dumps(txs)),
        )
        self.conn.commit()

    def get_blocks(self) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM chain_blocks ORDER BY height ASC")
        return [dict(row) for row in cur.fetchall()]

    # -----------------------------------------------------
    # Governance
    # -----------------------------------------------------
    def add_proposal(self, creator: str, title: str, desc: str, params: dict):
        self.conn.execute(
            "INSERT INTO governance_proposals (creator,title,description,params,status,votes) "
            "VALUES (?,?,?,?,?,?)",
            (creator, title, desc, json.dumps(params), "open", json.dumps({})),
        )
        self.conn.commit()

    def update_proposal(self, pid: int, status: str, votes: dict):
        self.conn.execute(
            "UPDATE governance_proposals SET status=?, votes=? WHERE id=?",
            (status, json.dumps(votes), pid),
        )
        self.conn.commit()

    def get_proposals(self) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM governance_proposals ORDER BY id ASC")
        return [dict(row) for row in cur.fetchall()]

    # -----------------------------------------------------
    # PoH
    # -----------------------------------------------------
    def record_poh_event(self, user: str, tier: int, metadata: dict):
        self.conn.execute(
            "INSERT INTO poh_events (user,tier,metadata) VALUES (?,?,?)",
            (user, tier, json.dumps(metadata)),
        )
        self.conn.commit()

    # -----------------------------------------------------
    # Maintenance
    # -----------------------------------------------------
    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass
