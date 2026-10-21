"""genesis-report / event_log: append-only event log for the GENESIS assistant.

Other modules call log_event() to record what happened; daily_report.py turns
the log into the Markdown report father reads.

Storage: one JSON object per line in events.jsonl (UTC timestamps, ISO-8601).
Append-only: this module never edits or deletes lines — only appends.

Code is 100% technical English. Output strings (the report body) may carry
Persian text supplied by callers; code itself stays English.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__version__ = "1.0.0"

DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "events.jsonl"


def _utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with millisecond precision, Z suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _resolve_log_path(log_path: Optional[str] = None) -> Path:
    if log_path is not None:
        return Path(log_path)
    env_path = os.environ.get("GENESIS_EVENT_LOG")
    if env_path:
        return Path(env_path)
    return DEFAULT_LOG_PATH


def log_event(category: str, summary: str, detail: Optional[Dict[str, Any]] = None,
              log_path: Optional[str] = None) -> dict:
    """Append one event to the log.

    Args:
        category: short category label, e.g. "build", "web", "error", "note".
        summary: one-line human-readable summary (Persian or English).
        detail: optional dict of extra structured data (must be JSON-serializable).
        log_path: optional override for the events.jsonl location.

    Returns:
        dict with status="logged", the event id, timestamp and log path.

    Raises:
        ValueError: on empty category/summary, non-dict detail, or a detail
            dict that cannot be serialized to JSON.
    """
    if not isinstance(category, str) or not category.strip():
        raise ValueError("category must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")
    if detail is None:
        detail = {}
    if not isinstance(detail, dict):
        raise ValueError("detail must be a dict or None")

    event = {
        "id": uuid.uuid4().hex,
        "timestamp": _utc_now_iso(),
        "category": category.strip(),
        "summary": summary.strip(),
        "detail": detail,
    }
    try:
        line = json.dumps(event, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("detail must be JSON-serializable: %s" % exc) from exc

    path = _resolve_log_path(log_path)
    if path.parent != Path(".") and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return {
        "status": "logged",
        "id": event["id"],
        "timestamp": event["timestamp"],
        "log_path": str(path),
    }


def read_events(log_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read all events from the log, oldest first.

    Blank lines and malformed lines are skipped (the log is append-only, so a
    corrupt line is left in place, never repaired or deleted). Returns an empty
    list when the log file does not exist yet.
    """
    path = _resolve_log_path(log_path)
    events: List[Dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and "timestamp" in event:
                events.append(event)
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events
