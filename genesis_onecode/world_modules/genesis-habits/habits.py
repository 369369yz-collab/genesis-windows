"""Habit learner for GENESIS.

Feeds from the genesis-report event log (events.jsonl). Observes events,
detects repeating patterns, and creates PROPOSALS. FAIL-CLOSED by design:

  - A proposal is only ever a suggestion. It NEVER executes anything.
  - Only an explicit approve(proposal_id) call arms an automation
    (status "approved"); the armed action is then owned by the scheduler
    module -- this module still never runs anything by itself.
  - Default state is proposal-only. reject(proposal_id) dismisses a proposal.

TOTAL EXCEPTION BOUNDARY (round-3 fix):
  Every public API (observe, ingest_events_jsonl, detect_patterns,
  list_proposals, approve, reject) is wrapped in a @_public decorator that
  catches Exception at the outermost layer and converts it to the standard
  error dict {"status": "error", "error": "..."}. RecursionError, TypeError,
  ValueError, OSError, and sqlite3.Error can NEVER escape a public API --
  hostile input always yields an error dict, never a crash. Specific inner
  guards remain where the error message matters (bad ts, unusable path,
  per-line JSONL skips, bad proposal_id/status); the boundary is the
  class-closing backstop for any exception type a future input can produce.
  MemoryError, KeyboardInterrupt, and SystemExit intentionally propagate
  (they are never swallowed).

100% technical English. No network calls.
"""

import functools
import json
import math
import os
import sqlite3
import time
import uuid
from pathlib import Path

_DB_NAME = "genesis_habits.db"

# Pattern detection thresholds.
MIN_REPEATS = 3          # occurrences before a pattern is proposed
WINDOW_DAYS = 7.0        # rolling window for counting repeats

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc REAL NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_obs_cat_ts ON observations(category, ts_utc);
CREATE INDEX IF NOT EXISTS idx_obs_sum_ts ON observations(summary, ts_utc);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    created_utc REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',  -- proposed|approved|rejected
    pattern_key TEXT NOT NULL,                 -- length-prefixed "n:categorym:summary" (collision-free)
    title TEXT NOT NULL,
    rationale TEXT NOT NULL,
    suggested_action_json TEXT NOT NULL DEFAULT '{}',
    decided_utc REAL,
    evidence_json TEXT NOT NULL DEFAULT '[]'
);
"""


class _DBError(Exception):
    """Internal: _connect() failed. Public APIs catch this and return an
    error dict -- it must never propagate to a caller."""


def _open_or_error(db_path):
    """Return (conn, None) on success or (None, error_dict) on failure.
    Guarantees no _DBError/TypeError/ValueError/OperationalError escapes."""
    try:
        return _connect(db_path), None
    except _DBError as exc:
        return None, {"status": "error", "error": str(exc)}


def _public(func):
    """Total exception boundary for every public API.

    Catches Exception at the outermost layer of the wrapped function and
    converts it to the standard error dict, so NO exception type
    (RecursionError, TypeError, ValueError, OSError, sqlite3.Error, ...)
    can escape to a caller. MemoryError is re-raised by design; so are
    KeyboardInterrupt and SystemExit (BaseException, never caught here).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except MemoryError:
            raise
        except Exception as exc:  # noqa: BLE001 - boundary is the point
            return {"status": "error",
                    "error": "%s: %s" % (type(exc).__name__, exc)}
    return wrapper


def _connect(db_path=None):
    """Open (creating) the habits SQLite DB. INTERNAL -- public callers wrap
    this and translate _DBError into an error dict; the exception is never
    exposed past a public API boundary."""
    if db_path is not None and not isinstance(db_path, (str, bytes, os.PathLike)):
        # Path() raises TypeError (not OSError) for int/dict/list/object --
        # validate up front so the public API fails closed with an error dict.
        raise _DBError("db_path must be a file path, got %r" % (db_path,))
    try:
        path = Path(db_path) if db_path else Path(__file__).resolve().parent / _DB_NAME
    except (TypeError, ValueError) as exc:
        # NUL byte / unusable os.PathLike: Path() raises ValueError, never OSError.
        raise _DBError("db_path is not a usable path: %s" % exc)
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
    except (OSError, sqlite3.Error) as exc:
        # Unwritable location, missing parent dir, /proc-like special path --
        # all surface as OperationalError, not OSError.
        raise _DBError("cannot open habits database %r: %s" % (str(path), exc))
    return conn


@_public
def observe(event, db_path=None):
    """Record one event from the report event log.

    event: {"category": str, "summary": str, "detail": dict, "ts": float|None}.
    "ts" is a UTC epoch; defaults to now. Returns {"status":"ok","id":...}.
    """
    if not isinstance(event, dict):
        return {"status": "error", "error": "event must be a dict"}
    category = event.get("category")
    summary = event.get("summary")
    if not category or not isinstance(category, str):
        return {"status": "error", "error": "event.category must be a non-empty string"}
    if not summary or not isinstance(summary, str):
        return {"status": "error", "error": "event.summary must be a non-empty string"}
    detail = event.get("detail") or {}
    ts = event.get("ts")
    if ts is None:
        ts = time.time()
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return {"status": "error",
                "error": "event.ts must be a numeric epoch, got %r" % (ts,)}
    if not math.isfinite(ts):
        # NaN crashes SQLite (stored as NULL, violating NOT NULL); inf
        # pollutes the 7-day window math. Reject non-finite epochs.
        return {"status": "error",
                "error": "event.ts must be a finite epoch, got %r" % (ts,)}
    try:
        detail_json = json.dumps(detail, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError) as exc:
        # RecursionError (NOT a ValueError) on deeply-nested detail; the
        # @_public boundary below would also catch it, but the specific
        # message is worth keeping.
        return {"status": "error", "error": "event.detail is not JSON-serializable: %s" % exc}
    conn, db_err = _open_or_error(db_path)
    if db_err:
        return db_err
    try:
        cur = conn.execute(
            "INSERT INTO observations (ts_utc, category, summary, detail_json)"
            " VALUES (?, ?, ?, ?)",
            (ts, category, summary, detail_json),
        )
        conn.commit()
        obs_id = cur.lastrowid
    finally:
        conn.close()
    return {"status": "ok", "id": obs_id}


@_public
def ingest_events_jsonl(path, db_path=None):
    """Read a genesis-report events.jsonl file and observe() each line.

    Returns {"status":"ok","ingested":N,"skipped":M}. Skipped lines are
    malformed JSON or invalid events -- never fatal. A missing file or an
    unusable path is an error dict, not an exception.
    """
    ingested = 0
    skipped = 0
    if not isinstance(path, (str, bytes, os.PathLike)):
        # open() raises TypeError (not OSError) for None/objects; fail closed.
        return {"status": "error",
                "error": "events path must be a file path, got %r" % (path,)}
    db_conn, db_err = _open_or_error(db_path)
    if db_err:
        return db_err
    db_conn.close()
    try:
        fh = open(path, "r", encoding="utf-8")
    except (OSError, ValueError, TypeError) as exc:
        # OSError: missing file, permission, directory. ValueError: NUL byte
        # in the path ("embedded null byte") or other invalid open() args.
        # TypeError: broken os.PathLike whose __fspath__() returns
        # non-str/bytes or raises internally (round-2 re-review finding 1).
        return {"status": "error",
                "error": "cannot read events file %r: %s" % (path, exc)}
    with fh:
        try:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, RecursionError):
                    # JSONDecodeError (a ValueError) on malformed lines; the
                    # hostile line is skipped and counted, never fatal.
                    # RecursionError (NOT a ValueError) on deeply-nested JSON
                    # (round-2 re-review finding 2) -- same skip behavior.
                    skipped += 1
                    continue
                res = observe(event, db_path=db_path)
                if res["status"] == "ok":
                    ingested += 1
                else:
                    skipped += 1
        except (OSError, ValueError) as exc:
            # Read-time failures are NOT covered by the open() guard above:
            # UnicodeDecodeError (a ValueError) on binary/invalid-UTF-8 data,
            # OSError [Errno 5] on /proc/self/mem-style special files.
            # Never fatal: report counts gathered so far as an error dict.
            return {"status": "error",
                    "error": "cannot read events file %r: %s" % (path, exc),
                    "ingested": ingested, "skipped": skipped}
    return {"status": "ok", "ingested": ingested, "skipped": skipped}


def _find_patterns(conn, now):
    """Detect (category, summary) pairs repeating >= MIN_REPEATS within WINDOW_DAYS."""
    cutoff = now - WINDOW_DAYS * 86400.0
    rows = conn.execute(
        """SELECT category, summary, COUNT(*) AS n,
                  MIN(ts_utc) AS first_ts, MAX(ts_utc) AS last_ts
           FROM observations WHERE ts_utc >= ?
           GROUP BY category, summary HAVING COUNT(*) >= ?
           ORDER BY n DESC""",
        (cutoff, MIN_REPEATS),
    ).fetchall()
    return rows


@_public
def detect_patterns(db_path=None):
    """Scan observations and create proposals for repeating patterns.

    Already-proposed pattern_keys are never re-proposed. Proposals are
    inert suggestions -- this function creates records only; it executes
    nothing and arms nothing.
    Returns {"status":"ok","new_proposals":[...],"existing_open":N}.
    """
    now = time.time()
    conn, db_err = _open_or_error(db_path)
    if db_err:
        return db_err
    try:
        pattern_rows = _find_patterns(conn, now)
        existing = {
            r["pattern_key"]
            for r in conn.execute(
                "SELECT pattern_key FROM proposals WHERE status = 'proposed'"
            ).fetchall()
        }
        new_proposals = []
        for prow in pattern_rows:
            # Unambiguous composite key: length-prefixed, so ("a|b","x") and
            # ("a","b|x") can never collide.
            key = "%d:%s%d:%s" % (len(prow["category"]), prow["category"],
                                  len(prow["summary"]), prow["summary"])
            if key in existing:
                continue
            pid = uuid.uuid4().hex[:16]
            title = "Recurring: %s -- %s" % (prow["category"], prow["summary"])
            rationale = (
                "Observed %d similar events in the last %.0f days "
                "(first %.0f, last %.0f UTC epoch)."
                % (prow["n"], WINDOW_DAYS, prow["first_ts"], prow["last_ts"])
            )
            evidence = [
                {
                    "category": prow["category"],
                    "summary": prow["summary"],
                    "occurrences": prow["n"],
                    "window_days": WINDOW_DAYS,
                }
            ]
            conn.execute(
                """INSERT INTO proposals
                   (id, created_utc, status, pattern_key, title, rationale,
                    suggested_action_json, evidence_json)
                   VALUES (?, ?, 'proposed', ?, ?, ?, ?, ?)""",
                (
                    pid,
                    now,
                    key,
                    title,
                    rationale,
                    json.dumps(
                        {
                            "type": "schedule_or_remind",
                            "note": "Concrete automation is defined at approve() "
                            "time; nothing is armed while status is 'proposed'.",
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
            new_proposals.append({"id": pid, "title": title, "rationale": rationale})
        conn.commit()
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM proposals WHERE status = 'proposed'"
        ).fetchone()["c"]
    finally:
        conn.close()
    return {"status": "ok", "new_proposals": new_proposals, "existing_open": open_count}


@_public
def list_proposals(status=None, db_path=None):
    """List proposals, optionally filtered by status (proposed|approved|rejected)."""
    if status is not None and not isinstance(status, str):
        # A dict/list status would raise sqlite3.ProgrammingError on binding;
        # validate before it ever reaches a query.
        return {"status": "error",
                "error": "status must be a string or None, got %r" % (status,)}
    conn, db_err = _open_or_error(db_path)
    if db_err:
        return db_err
    try:
        if status:
            rows = conn.execute(
                "SELECT id, created_utc, status, title, rationale, decided_utc "
                "FROM proposals WHERE status = ? ORDER BY created_utc DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, created_utc, status, title, rationale, decided_utc "
                "FROM proposals ORDER BY created_utc DESC"
            ).fetchall()
    finally:
        conn.close()
    return {
        "status": "ok",
        "proposals": [
            {
                "id": r["id"],
                "status": r["status"],
                "title": r["title"],
                "rationale": r["rationale"],
                "created_utc": r["created_utc"],
                "decided_utc": r["decided_utc"],
            }
            for r in rows
        ],
    }


@_public
def approve(proposal_id, db_path=None):
    """Arm an automation proposal. FAIL-CLOSED: this is the ONLY call that
    moves a proposal to "approved". It records the decision; the armed
    automation is picked up by the scheduler layer -- this module still
    executes nothing by itself.

    Returns {"status":"ok","id":...} or {"status":"error",...}.
    """
    if proposal_id is not None and not isinstance(proposal_id, (str, int)):
        # A dict/list/object proposal_id raises sqlite3.ProgrammingError on
        # binding -- validate BEFORE any query touches it.
        return {"status": "error",
                "error": "proposal_id must be a string or int, got %r" % (proposal_id,)}
    conn, db_err = _open_or_error(db_path)
    if db_err:
        return db_err
    try:
        row = conn.execute(
            "SELECT status FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return {"status": "error", "error": "unknown proposal_id"}
        if row["status"] != "proposed":
            return {
                "status": "error",
                "error": "proposal is '%s', only 'proposed' can be approved"
                % row["status"],
            }
        conn.execute(
            "UPDATE proposals SET status = 'approved', decided_utc = ? WHERE id = ?",
            (time.time(), proposal_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "id": proposal_id, "state": "approved"}


@_public
def reject(proposal_id, db_path=None):
    """Dismiss a proposal. Irreversible by design (decision is recorded)."""
    if proposal_id is not None and not isinstance(proposal_id, (str, int)):
        # A dict/list/object proposal_id raises sqlite3.ProgrammingError on
        # binding -- validate BEFORE any query touches it.
        return {"status": "error",
                "error": "proposal_id must be a string or int, got %r" % (proposal_id,)}
    conn, db_err = _open_or_error(db_path)
    if db_err:
        return db_err
    try:
        row = conn.execute(
            "SELECT status FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return {"status": "error", "error": "unknown proposal_id"}
        if row["status"] != "proposed":
            return {
                "status": "error",
                "error": "proposal is '%s', only 'proposed' can be rejected"
                % row["status"],
            }
        conn.execute(
            "UPDATE proposals SET status = 'rejected', decided_utc = ? WHERE id = ?",
            (time.time(), proposal_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "id": proposal_id, "state": "rejected"}
