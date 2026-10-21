"""genesis-report / daily_report: Markdown daily report for father.

generate_report(date_str) reads events.jsonl (via event_log.read_events),
filters to the requested UTC calendar day, groups by category, and returns a
Markdown string. Persian text in event summaries passes through untouched —
this is the "Persian allowed in OUTPUT strings only" case; code stays English.

No fabricated content: a day with no events produces an honest "no events"
report, never invented activity.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date
from typing import Any, Dict, List, Optional

from event_log import read_events

__version__ = "1.0.0"


def _parse_date(date_str: str) -> date:
    if not isinstance(date_str, str):
        raise ValueError("date_str must be a string in 'YYYY-MM-DD' format")
    parts = date_str.split("-")
    if len(parts) != 3:
        raise ValueError("date_str must be in 'YYYY-MM-DD' format, got: %r" % date_str)
    try:
        year, month, day = (int(p) for p in parts)
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError("date_str must be a real calendar date 'YYYY-MM-DD', got: %r" % date_str) from exc


def _format_detail(detail: Any) -> str:
    """Render the detail dict as compact sub-bullets; empty dict -> ''."""
    if not detail:
        return ""
    try:
        text = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = repr(detail)
    return "  - detail: `%s`" % text


def generate_report(date_str: str, log_path: Optional[str] = None) -> str:
    """Build the Markdown daily report for one UTC calendar day.

    Args:
        date_str: the day to report, 'YYYY-MM-DD' (interpreted in UTC).
        log_path: optional override for the events.jsonl location.

    Returns:
        str: Markdown report. Events are grouped by category; a day with no
        events yields an honest empty-day report.

    Raises:
        ValueError: when date_str is not a valid 'YYYY-MM-DD' date.
    """
    day = _parse_date(date_str)
    prefix = day.isoformat()

    day_events = [e for e in read_events(log_path)
                  if isinstance(e.get("timestamp"), str) and e["timestamp"].startswith(prefix)]

    lines: List[str] = []
    lines.append("# GENESIS daily report — %s" % day.isoformat())
    lines.append("")
    lines.append("Timezone: UTC. Generated from the append-only event log.")
    lines.append("")

    if not day_events:
        lines.append("No events were recorded on this day.")
        lines.append("")
        return "\n".join(lines)

    grouped: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for event in day_events:
        grouped.setdefault(str(event.get("category", "uncategorized")), []).append(event)

    lines.append("Total events: %d" % len(day_events))
    lines.append("")
    for category, items in grouped.items():
        lines.append("## %s (%d)" % (category, len(items)))
        lines.append("")
        for event in items:
            timestamp = event.get("timestamp", "")
            clock = timestamp[11:16] if len(timestamp) >= 16 else timestamp
            lines.append("- **%s UTC** — %s" % (clock, event.get("summary", "")))
            detail_line = _format_detail(event.get("detail"))
            if detail_line:
                lines.append(detail_line)
        lines.append("")

    lines.append("---")
    lines.append("End of report. Source: events.jsonl (append-only).")
    return "\n".join(lines)
