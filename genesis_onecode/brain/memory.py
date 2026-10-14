"""GENESIS long-term memory — SQLite, local, private.

Lives at <GENESIS_DATA_DIR>/memory/genesis.db. Two tables:

  facts(key TEXT PRIMARY KEY, value TEXT, updated_at REAL)
      — durable things GENESIS must not forget (names, preferences,
        decisions). Written explicitly, never guessed.

  exchanges(id INTEGER PRIMARY KEY, role TEXT, content TEXT, ts REAL)
      — chat history. The /chat endpoint feeds the last N exchanges
        to the local LLM as conversation context.

Stdlib only (sqlite3). Thread-safe via a lock. WAL mode for
crash safety. Nothing leaves the machine.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exchanges(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exchanges_ts ON exchanges(ts);
"""

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _db_path() -> Path:
    base = Path(os.environ.get("GENESIS_DATA_DIR", "genesis_data"))
    d = base / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / "genesis.db"


def _conn() -> sqlite3.Connection:
    global _db
    with _lock:
        if _db is None:
            _db = sqlite3.connect(str(_db_path()), check_same_thread=False)
            _db.execute("PRAGMA journal_mode=WAL;")
            _db.executescript(_SCHEMA)
            _db.commit()
        return _db


# ---- facts --------------------------------------------------------------
def remember(key: str, value: str) -> None:
    """Store a durable fact. Key and value are explicit — never guessed."""
    key, value = str(key).strip(), str(value).strip()
    if not key:
        raise ValueError("empty memory key")
    c = _conn()
    with _lock:
        c.execute(
            "INSERT INTO facts(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at",
            (key, value, time.time()),
        )
        c.commit()


def recall(key: str, default: str = "") -> str:
    c = _conn()
    with _lock:
        row = c.execute("SELECT value FROM facts WHERE key=?",
                        (str(key).strip(),)).fetchone()
    return row[0] if row else default


def forget(key: str) -> bool:
    c = _conn()
    with _lock:
        cur = c.execute("DELETE FROM facts WHERE key=?", (str(key).strip(),))
        c.commit()
        return cur.rowcount > 0


def all_facts() -> dict:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT key, value FROM facts ORDER BY updated_at DESC").fetchall()
    return {k: v for k, v in rows}


# ---- exchanges ----------------------------------------------------------
def log_exchange(role: str, content: str) -> None:
    if role not in ("user", "her"):
        raise ValueError("role must be 'user' or 'her'")
    c = _conn()
    with _lock:
        c.execute("INSERT INTO exchanges(role,content,ts) VALUES(?,?,?)",
                  (role, str(content)[:20000], time.time()))
        c.commit()


def recent_exchanges(n: int = 12) -> list[dict]:
    """Last n exchanges, oldest-first, for LLM context."""
    n = max(1, min(int(n), 50))
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT role, content FROM exchanges ORDER BY id DESC LIMIT ?",
            (n,)).fetchall()
    return [{"role": ("assistant" if r == "her" else "user"), "content": t}
            for r, t in reversed(rows)]


def prune_exchanges(keep: int = 500) -> int:
    """Keep the newest `keep` exchanges; returns rows deleted."""
    c = _conn()
    with _lock:
        cur = c.execute(
            "DELETE FROM exchanges WHERE id NOT IN "
            "(SELECT id FROM exchanges ORDER BY id DESC LIMIT ?)", (keep,))
        c.commit()
        return cur.rowcount
