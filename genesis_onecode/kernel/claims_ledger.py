"""kernel/claims_ledger.py — the append-only claims ledger (anti-fabrication).

Adapter, not rewrite: the truth lives in genesis_final/brain/truth_layer.py
(FabricationError, evidence hashing). This module wraps it in the kernel's own
SQLite ledger so the kernel audits what she claimed and what proved it.

report_completion(claim, evidence) raises FabricationError on missing evidence —
the brain literally cannot say «انجam شد» without proof. (Said properly: done
is never claimed without evidence.)
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))

# Adapter: the anti-fabrication primitives live in the 369 world's brain.
_TRUTH_PATH = os.path.expanduser("~/workspace/genesis_final/brain")
if _TRUTH_PATH not in sys.path:
    sys.path.insert(0, _TRUTH_PATH)

from truth_layer import FabricationError, evidence_hash_of  # noqa: E402

# Re-export: the kernel's callers catch this exact class.
__all__ = ["ClaimsLedger", "FabricationError", "report_completion"]

DEFAULT_DB = os.path.join(_HERE, "claims_ledger.db")


class ClaimsLedger:
    """Append-only SQLite ledger: every factual claim + its evidence hash."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS claims_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        claim TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        verdict TEXT NOT NULL,          -- completion_accepted | completion_blocked
        reason TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_ledger_ts ON claims_ledger(ts);
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.environ.get("GENESIS_CLAIMS_DB") or DEFAULT_DB
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._connect() as con:
            con.executescript(self.SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _insert(self, claim: str, evidence_hash: str,
                verdict: str, reason: str = "") -> int:
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO claims_ledger (ts, claim, evidence_hash, verdict, reason)"
                " VALUES (?,?,?,?,?)",
                (time.time(), claim, evidence_hash, verdict, reason))
            return cur.lastrowid

    def report_completion(self, claim: str, evidence: Any = None) -> str:
        """The ONE sanctioned way for the kernel to say something is done.

        Raises FabricationError when evidence is missing or empty (delegated
        to truth_layer.report_completion — fail closed), and records the
        accepted completion in the append-only ledger.
        """
        ev_hash = evidence_hash_of({"evidence": evidence}) if evidence is not None else None
        try:
            # truth_layer's report_completion raises FabricationError on
            # missing/empty evidence and returns the claim's hash otherwise.
            from truth_layer import report_completion as _tl_report
            result = _tl_report(claim, evidence)
        except FabricationError:
            self._insert(claim, ev_hash or "none", "completion_blocked",
                         "evidence missing or empty — refused")
            raise
        self._insert(claim, result, "completion_accepted",
                     "evidence present, hash recorded")
        return result

    def audit(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, ts, claim, evidence_hash, verdict, reason"
                " FROM claims_ledger ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "ts": r[1], "claim": r[2],
                 "evidence_hash": r[3], "verdict": r[4], "reason": r[5]}
                for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._connect() as con:
            total = con.execute("SELECT COUNT(*) FROM claims_ledger").fetchone()[0]
            acc = con.execute("SELECT COUNT(*) FROM claims_ledger"
                              " WHERE verdict='completion_accepted'").fetchone()[0]
            blk = con.execute("SELECT COUNT(*) FROM claims_ledger"
                              " WHERE verdict='completion_blocked'").fetchone()[0]
        return {"total": total, "accepted": acc, "blocked": blk}


def report_completion(claim: str, evidence: Any = None,
                      db_path: Optional[str] = None) -> str:
    """Module-level convenience: raise on missing evidence, else ledger it."""
    return ClaimsLedger(db_path=db_path).report_completion(claim, evidence)
