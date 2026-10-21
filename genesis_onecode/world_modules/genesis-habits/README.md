# genesis-habits — Habit Learner

## What it does
Watches GENESIS's behavior (fed from the genesis-report event log), detects
repeating patterns, and creates **proposals** — never automations.
FAIL-CLOSED by design: proposals never auto-execute; only an explicit
`approve(proposal_id)` call arms one (status `"approved"`), and even then this
module executes nothing — the armed automation is picked up by the scheduler
layer. The default state is proposal-only.

## Architecture
- `habits.py`, SQLite store (`genesis_habits.db`, two tables: `observations`,
  `proposals`).
- `observe(event)` — records one event
  `{"category","summary","detail","ts"}`; invalid events rejected, never fatal.
- `ingest_events_jsonl(path)` — bulk-feed from a genesis-report `events.jsonl`
  (malformed lines counted as skipped, never fatal).
- `detect_patterns()` — finds (category, summary) pairs repeating >= 3 times
  in a rolling 7-day window; creates one proposal per pattern, never
  re-proposes an open one, and returns `{"new_proposals":[...],"existing_open":N}`.
  It only writes proposal records — executes nothing.
- `list_proposals(status=None)` — inspect proposed/approved/rejected.
- `approve(proposal_id)` — the ONLY transition proposed -> approved. Errors on
  unknown ids and non-proposed states (fail-closed, no silent no-ops).
- `reject(proposal_id)` — dismisses; decision recorded, id is unusable after.

## Bridge call points
None in this module. Approved proposals are consumed by the scheduler module
(not part of this build). This module makes zero network calls.

## What's real vs what's stub
- REAL: event observation, pattern detection thresholds, proposal lifecycle,
  fail-closed approve/reject, JSONL ingestion.
- NOT CLAIMED / NOT DONE: no actual automation execution exists here
  (by design); the scheduler-side consumer of "approved" proposals is a
  separate module. Thresholds (3 repeats / 7 days) are heuristics, documented
  in code constants.

## Windows-only notes
No Windows-only APIs. SQLite + stdlib; developed and tested on Linux, runs
identically on Windows 10/11 Python 3.12. No mocks needed — the module is
platform-agnostic by design.

## API reference
```python
observe(event)                         -> {"status":"ok","id":..}
ingest_events_jsonl(path)              -> {"status":"ok","ingested":N,"skipped":M}
detect_patterns()                      -> {"status":"ok","new_proposals":[...],"existing_open":N}
list_proposals(status=None)            -> {"status":"ok","proposals":[...]}
approve(proposal_id)                   -> {"status":"ok","id":..,"state":"approved"}
reject(proposal_id)                    -> {"status":"ok","id":..,"state":"rejected"}
```
