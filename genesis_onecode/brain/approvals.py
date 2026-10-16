"""approvals.py — YZ's approval gates, as code.

The approval-first law: money moves, publishing, and irreversible actions
need YZ's explicit approval FIRST. This module is the queue:

  request_approval(lease_id, action, detail, agent_id) -> approval id
      Called when a GENIUS agent attempts a sensitive action. The action is
      DENIED for now (fail-closed); YZ decides later.

  pending() -> list of awaiting approvals (for the UI).

  decide(approval_id, approved) -> the verdict is recorded; when approved,
      the governor's cached denial for that lease+action is flipped to
      APPROVED so the agent's retry succeeds.

  check(lease_id, action) -> True when a recorded APPROVED verdict exists.

Stdlib only, SQLite in the same genesis.db.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
import os

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals(
  id TEXT PRIMARY KEY,
  lease_id TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  agent_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at REAL NOT NULL,
  decided_at REAL
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
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


def request_approval(lease_id: str, action: str, detail: str = "",
                     agent_id: str = "") -> str:
    """File a new approval request. Returns its id. The action stays denied."""
    aid = "appr-" + uuid.uuid4().hex[:8]
    c = _conn()
    with _lock:
        # don't spam YZ with duplicates for the same lease+action
        row = c.execute(
            "SELECT id FROM approvals WHERE lease_id=? AND action=?"
            " AND status='pending'", (lease_id, action)).fetchone()
        if row:
            return row[0]
        c.execute(
            "INSERT INTO approvals(id,lease_id,action,detail,agent_id,"
            "status,created_at) VALUES(?,?,?,?,?,'pending',?)",
            (aid, lease_id, action, str(detail)[:1000], agent_id, time.time()))
        c.commit()
    try:
        from brain import memory as _mem
        _mem.log_exchange(
            "her", f"YZ, one of my agents needs your approval: {action} "
            f"({detail[:120]}). Check the approvals panel, پدر.")
    except Exception:
        pass
    return aid


def pending() -> list[dict]:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT id,lease_id,action,detail,agent_id,status,created_at"
            " FROM approvals WHERE status='pending' ORDER BY created_at"
        ).fetchall()
    keys = ("id", "lease_id", "action", "detail", "agent_id", "status",
            "created_at")
    return [dict(zip(keys, r)) for r in rows]


def decide(approval_id: str, approved: bool) -> dict | None:
    """YZ decides. Returns the record, or None if unknown."""
    c = _conn()
    with _lock:
        row = c.execute(
            "SELECT id,lease_id,action,detail,agent_id,status,created_at"
            " FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not row:
            return None
        if row[5] != "pending":
            keys = ("id", "lease_id", "action", "detail", "agent_id",
                    "status", "created_at")
            return dict(zip(keys, row))
        c.execute(
            "UPDATE approvals SET status=?, decided_at=? WHERE id=?",
            ("approved" if approved else "denied", time.time(), approval_id))
        c.commit()
    try:
        from brain import memory as _mem
        _mem.remember(f"approval_{approval_id}",
                      f"YZ {'approved' if approved else 'denied'}: "
                      f"{row[2]} ({row[3][:120]})")
    except Exception:
        pass
    keys = ("id", "lease_id", "action", "detail", "agent_id", "status",
            "created_at")
    rec = dict(zip(keys, row))
    rec["status"] = "approved" if approved else "denied"
    return rec


def is_approved(lease_id: str, action: str) -> bool:
    c = _conn()
    with _lock:
        row = c.execute(
            "SELECT id FROM approvals WHERE lease_id=? AND action=?"
            " AND status='approved'", (lease_id, action)).fetchone()
    return row is not None
