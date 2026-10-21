# genesis-report v1.0.0

GENESIS's daily report: an append-only event log plus the Markdown report
father reads every day.

## What it does

- `event_log.log_event(category, summary, detail=None)` — appends one event to
  `events.jsonl` (one JSON object per line, UTC ISO-8601 timestamps). Returns
  `{"status": "logged", "id": ..., "timestamp": ..., "log_path": ...}`.
- `event_log.read_events()` — reads the log oldest-first; skips blank and
  malformed lines without ever editing the file.
- `daily_report.generate_report(date_str)` — builds a Markdown report for one
  UTC day (`'YYYY-MM-DD'`), grouped by category with UTC clock times. A day
  with no events yields an honest empty-day report — never invented activity.

Persian text in event summaries passes through into the report untouched.
Code itself is 100% technical English.

## Architecture

```
genesis-report/
  event_log.py            append-only JSONL log (log_event / read_events)
  daily_report.py         Markdown report builder (generate_report)
  events.jsonl            created at runtime; never shipped with content
  tests/test_report.py    pytest suite (11 tests)
  test_logs/              three independent green pytest runs
  windows_smoke_test.py   quick API check for the Windows runner
  requirements.txt        stdlib only
```

Other modules (eyes, hands, voice, ...) call `log_event()` to record what
happened; the report is the read side. The log is append-only by design:
no function in this module edits or deletes lines.

The log location defaults to `events.jsonl` next to the module and can be
overridden per-call (`log_path=...`) or via the `GENESIS_EVENT_LOG`
environment variable.

## Bridge call points

None. This module is fully local — it writes and reads a local JSONL file.
Nothing leaves the machine.

## What's real vs what's stub

| Piece | Status |
|---|---|
| `log_event()` append + validation | REAL — tested, incl. JSON-serializability guard |
| UTC timestamps | REAL — timezone-aware, asserted in tests |
| `read_events()` ordering + corruption tolerance | REAL — tested |
| `generate_report()` grouping/filtering | REAL — tested, incl. cross-day boundary |
| Empty-day report | REAL — honest "no events" text, tested |
| Persian summary pass-through | REAL — tested with a Persian sample |

No stubs, no network calls, no placeholders. The only thing not shipped is
data: `events.jsonl` starts empty on the target machine.

## Windows-only notes

None — the module is pure stdlib and behaves identically on Windows and
Linux. `windows_smoke_test.py` runs on the Windows runner as a sanity check.

## API reference

```python
from event_log import log_event, read_events
from daily_report import generate_report

result = log_event("build", "eyes module finished", {"tests": 11})
# {"status": "logged", "id": "9f3c...", "timestamp": "2026-10-13T10:00:00.000Z",
#  "log_path": ".../events.jsonl"}

events = read_events()                       # list of dicts, oldest first

markdown: str = generate_report("2026-10-13")
```

Raises: `ValueError` on empty category/summary, non-dict or non-serializable
detail, and on a `date_str` that is not a real `'YYYY-MM-DD'` calendar date.
