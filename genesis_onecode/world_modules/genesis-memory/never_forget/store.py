"""NEVER-FORGET memory core — portable, pure stdlib, Windows-safe.

Event-sourced open-loop store: every line of the JSONL file is an event.
Current state of a loop = its LAST event. Lines are never deleted;
a closed loop stays in history forever.

Events:
  {"event": "open", "id": ..., "opened_ts": ..., "title": ..., "owner": ...,
   "deadline_ts": ...|null, "status": "open", "last_action_ts": ...,
   "evidence": ..., "source": ...}
  {"event": "action", "id": ..., "ts": ..., "note": ...}
  {"event": "close", "id": ..., "ts": ..., "status": "closed",
   "evidence": ..., "closed_by": ...}

Doctrine: storage is not memory. Memory is retrieval + enforcement.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_ts(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def load_loops(path):
    """Return {loop_id: current_state_dict} — last event per id wins."""
    path = Path(path)
    states = {}
    if not path.exists():
        return states
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            lid = ev.get("id")
            if not lid:
                continue
            kind = ev.get("event", "open")
            if kind == "open":
                states[lid] = {
                    "id": lid,
                    "title": ev.get("title", ""),
                    "owner": ev.get("owner", ""),
                    "opened_ts": ev.get("opened_ts"),
                    "deadline_ts": ev.get("deadline_ts"),
                    "status": "open",
                    "last_action_ts": ev.get("last_action_ts") or ev.get("opened_ts"),
                    "evidence": ev.get("evidence", ""),
                    "source": ev.get("source", ""),
                }
            elif kind == "action":
                st = states.get(lid)
                if st and st["status"] == "open":
                    ts = ev.get("ts")
                    if ts and (not st["last_action_ts"] or ts > st["last_action_ts"]):
                        st["last_action_ts"] = ts
                    note = ev.get("note", "")
                    if note:
                        st["evidence"] = (st["evidence"] + " | " + note).strip(" |")
            elif kind in ("pause", "update", "resume"):
                # YZ-ordered holds must be honored: a paused loop is intentionally
                # held, not forgotten. "update" carries an explicit status field.
                st = states.get(lid)
                if st:
                    if kind == "resume":
                        new_status = "open"
                    else:
                        new_status = ev.get("status") or ("paused" if kind == "pause" else None)
                    if new_status in ("open", "paused"):
                        st["status"] = new_status
                        if new_status == "paused":
                            st["paused_ts"] = ev.get("ts")
                    ts = ev.get("ts") or ev.get("last_action_ts")
                    if ts and (not st["last_action_ts"] or ts > st["last_action_ts"]):
                        st["last_action_ts"] = ts
                    note = ev.get("evidence", "")
                    if note:
                        tag = "PAUSED" if st["status"] == "paused" else "UPDATED"
                        if tag not in st["evidence"]:
                            st["evidence"] = (st["evidence"] + " | %s: " % tag + note).strip(" |")
            elif kind == "close":
                st = states.get(lid)
                if st:
                    st["status"] = "closed"
                    st["closed_ts"] = ev.get("ts")
                    st["close_evidence"] = ev.get("evidence", "")
                    st["closed_by"] = ev.get("closed_by", "")
    return states


def _append(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def open_loop(path, loop_id, title, owner, deadline_ts=None, evidence="", source=""):
    ts = now_iso()
    _append(path, {
        "event": "open",
        "id": loop_id,
        "opened_ts": ts,
        "title": title,
        "owner": owner,
        "deadline_ts": deadline_ts,
        "status": "open",
        "last_action_ts": ts,
        "evidence": evidence,
        "source": source,
    })


def record_action(path, loop_id, note=""):
    _append(path, {"event": "action", "id": loop_id, "ts": now_iso(), "note": note})


def close_loop(path, loop_id, evidence, closed_by=""):
    if not evidence:
        raise ValueError("close_loop requires evidence — a loop closes ONLY with proof of completion")
    _append(path, {
        "event": "close",
        "id": loop_id,
        "ts": now_iso(),
        "status": "closed",
        "evidence": evidence,
        "closed_by": closed_by,
    })


def open_ids(path):
    return [lid for lid, st in load_loops(path).items() if st["status"] == "open"]
