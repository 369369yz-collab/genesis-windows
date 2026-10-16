"""income.py — the income rails of the GENIUS agents.

The WOLF LAW: in making money GENESIS must be a wolf, not a sheep. Agents
hunt income in parallel, no cap. This module is the honest ledger:

  record_income(agent_id, mission_id, amount, currency, source, evidence)
      Only CONFIRMED income is recorded — evidence is required (YZ's
      confirmation or a receipt reference). Unconfirmed claims stay out.

  ledger() / total() — the transparent books.

  hunt() — the wolf hunt: generates income-seeking missions for the womb
      from real opportunity templates. The agents work them with browser
      hands; income lands in the ledger only when confirmed.

Money settles directly to YZ's accounts/wallets — agents never hold
customer funds (the codex denies 'spend' without his approval).
Stdlib only, SQLite in the same genesis.db.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS income(
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  mission_id TEXT NOT NULL DEFAULT '',
  amount REAL NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  source TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'confirmed',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_income_agent ON income(agent_id);
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


def record_income(agent_id: str, amount: float, currency: str = "USD",
                  source: str = "", evidence: str = "",
                  mission_id: str = "") -> dict:
    """Record CONFIRMED income. Evidence required — no evidence, no entry."""
    amount = float(amount)
    if amount <= 0:
        raise ValueError("income must be positive")
    if not str(evidence).strip():
        raise ValueError("income needs evidence (YZ confirmation or receipt)")
    iid = "inc-" + uuid.uuid4().hex[:8]
    c = _conn()
    with _lock:
        c.execute(
            "INSERT INTO income(id,agent_id,mission_id,amount,currency,"
            "source,evidence,status,created_at)"
            " VALUES(?,?,?,?,?, ?,?,'confirmed',?)",
            (iid, agent_id, mission_id, amount, currency[:8],
             str(source)[:300], str(evidence)[:1000], time.time()))
        try:
            # the womb owns the agents table; tolerate it not existing yet
            c.execute("UPDATE agents SET income = income + ? WHERE id=?",
                      (amount, agent_id))
        except sqlite3.OperationalError:
            pass
        c.commit()
        row = c.execute(
            "SELECT id,agent_id,mission_id,amount,currency,source,evidence,"
            "status,created_at FROM income WHERE id=?", (iid,)).fetchone()
    keys = ("id", "agent_id", "mission_id", "amount", "currency", "source",
            "evidence", "status", "created_at")
    try:
        from brain import memory as _mem
        _mem.remember(f"income_{iid}",
                      f"{agent_id} earned {amount} {currency} via {source}. "
                      f"Evidence: {evidence[:150]}")
    except Exception:
        pass
    return dict(zip(keys, row))


def ledger(limit: int = 50) -> list[dict]:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT id,agent_id,mission_id,amount,currency,source,evidence,"
            "status,created_at FROM income ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),)).fetchall()
    keys = ("id", "agent_id", "mission_id", "amount", "currency", "source",
            "evidence", "status", "created_at")
    return [dict(zip(keys, r)) for r in rows]


def total() -> dict:
    c = _conn()
    with _lock:
        rows = c.execute(
            "SELECT currency, SUM(amount), COUNT(*) FROM income"
            " GROUP BY currency").fetchall()
    return {cur: {"total": round(s, 2), "count": n} for cur, s, n in rows}


# ---- the wolf hunt -------------------------------------------------------------
# Opportunity templates — real kinds of online work a GENIUS agent can do
# with browser hands. The hunt turns them into womb missions; the agents
# work them; income is recorded ONLY when confirmed with evidence.

HUNT_TEMPLATES = [
    ("Research a trending topic and write a publish-ready article",
     "Pick a topic buzzing in gaming/cinema, research it with browser hands, "
     "write a complete article. Income when YZ approves it for the page."),
    ("Find freelance gigs matching the agent's skills",
     "Hunt freelance platforms for real gigs (writing, coding, research). "
     "Report the best matches with links — YZ decides which to take."),
    ("Build a small useful tool and document it",
     "Code something people need, document it honestly. Income via GENESIS "
     "package sales when YZ approves the package."),
]


def hunt() -> list[dict]:
    """Generate income-seeking missions. Returns the missions created."""
    from brain import womb as _womb
    _womb._conn()  # ensure the missions table exists (shared genesis.db)
    created = []
    for title, detail in HUNT_TEMPLATES:
        c = _conn()
        with _lock:
            dup = c.execute(
                "SELECT id FROM missions WHERE title=? AND status IN"
                " ('pending','active')", (title,)).fetchone()
        if dup:
            continue
        created.append(_womb.add_mission(title, detail + " [wolf-hunt]"))
    return created
