"""Local-first personal memory for GENESIS.

SQLite-backed key/value store with tag search. 100% technical English.
Nothing leaves this machine: see sync.py for the (explicit, bridge-gated)
path to the network mind.
"""

import json
import sqlite3
import time
from pathlib import Path

_DB_NAME = "genesis_memory.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_utc REAL NOT NULL,
    updated_utc REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_utc DESC);
"""


def _connect(db_path=None):
    path = Path(db_path) if db_path else Path(__file__).resolve().parent / _DB_NAME
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def remember(key, value, tags=None, db_path=None):
    """Store (or overwrite) a memory.

    Args:
        key: unique string identifier.
        value: any JSON-serializable value.
        tags: optional list of tag strings.
    Returns: {"status": "ok", "key": key} or {"status": "error", ...}.
    """
    if not isinstance(key, str) or not key:
        return {"status": "error", "error": "key must be a non-empty string"}
    tags = tags or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        return {"status": "error", "error": "tags must be a list of strings"}
    try:
        value_json = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return {"status": "error", "error": "value is not JSON-serializable: %s" % exc}
    now = time.time()
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT key FROM memories WHERE key = ?", (key,)
        )
        existed = cur.fetchone() is not None
        conn.execute(
            """INSERT INTO memories (key, value_json, tags_json, created_utc, updated_utc)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value_json=excluded.value_json,
                 tags_json=excluded.tags_json,
                 updated_utc=excluded.updated_utc""",
            (key, value_json, json.dumps(tags, ensure_ascii=False), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "status": "ok",
        "key": key,
        "action": "updated" if existed else "stored",
    }


def _score(query_words, key, value_json, tags):
    hay = " ".join([key, value_json, " ".join(tags)]).lower()
    score = 0
    for word in query_words:
        if word in hay:
            score += 1
        # phrase bonus: full query hit in key ranks highest
    return score


def recall(query, top_k=5, db_path=None):
    """Search memories by keyword match. Returns top_k matches, best first.

    Purely local scoring (substring match, key-weighted). No network calls.
    Returns: {"status": "ok", "results": [{"key","value","tags","score"}]}.
    """
    if not isinstance(query, str) or not query.strip():
        return {"status": "error", "error": "query must be a non-empty string"}
    words = query.lower().split()
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT key, value_json, tags_json FROM memories"
        ).fetchall()
    finally:
        conn.close()
    scored = []
    for row in rows:
        tags = json.loads(row["tags_json"])
        value_json = row["value_json"]
        score = _score(words, row["key"], value_json, tags)
        if row["key"].lower() == query.lower():
            score += 10  # exact key match wins
        if query.lower() in row["key"].lower():
            score += 3
        if score > 0:
            scored.append(
                {
                    "key": row["key"],
                    "value": json.loads(value_json),
                    "tags": tags,
                    "score": score,
                }
            )
    scored.sort(key=lambda r: r["score"], reverse=True)
    return {"status": "ok", "results": scored[: max(1, top_k)]}


def forget(key, db_path=None):
    """Delete a memory. Returns {"status":"ok"} even if the key did not exist
    (idempotent), with "existed" flag."""
    if not isinstance(key, str) or not key:
        return {"status": "error", "error": "key must be a non-empty string"}
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        conn.commit()
        deleted = cur.rowcount > 0
    finally:
        conn.close()
    return {"status": "ok", "key": key, "existed": deleted}


def list_tags(db_path=None):
    """Return the sorted set of all tags currently in use."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT tags_json FROM memories").fetchall()
    finally:
        conn.close()
    tags = set()
    for row in rows:
        for tag in json.loads(row["tags_json"]):
            tags.add(tag)
    return {"status": "ok", "tags": sorted(tags)}
