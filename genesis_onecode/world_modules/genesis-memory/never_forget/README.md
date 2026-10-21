# never_forget — portable memory-that-cannot-forget

Embedded inside the `genesis-memory` module so the extracted GENESIS
carries it with her: the Windows build never forgets either.

## What it is

An **event-sourced open-loop store** (`store.py`) + a **deterministic gate**
(`gate.py`). Pure Python stdlib — runs on Windows and Linux identically.

- `open_loops.jsonl` (this dir: `seed_loops.jsonl`): one JSON line per event.
  `open` → `action`* → `close`. Lines are **never deleted**; a closed loop
  stays in history forever. Current state = last event per loop id.
- A loop closes **only with evidence** (`close_loop` raises without it).
- The gate FAILS (loudly) when an open loop is idle > 24h or past deadline.
  No AI judgment — arithmetic only.

## Use inside GENESIS

```python
from never_forget import store, gate

store.open_loop("my-loop", "Do the thing", owner="genesis",
                deadline_ts="2026-10-20T12:00:00+03:30",
                evidence="why it opened", source="chat")
store.record_action("my-loop", note="half done")
result = gate.check("open_loops.jsonl")
print(gate.format_report(result))   # exit non-zero on server when failed
store.close_loop("my-loop", evidence="done: <proof>", closed_by="genesis")
```

On first boot GENESIS imports `seed_loops.jsonl` (synced from the 369
network at build time) so she wakes up already remembering every open loop.

## Server twin

`~/workspace/content_team/memory/never_forget_gate.py` is the server-side
CLI: it imports this exact package, prints the gate report, exits non-zero
on failure, and auto-escalates overdue loops to the Agent YZ decision queue
as P0 (idempotent — one escalation per loop).

## Doctrine

See `~/workspace/content_team/memory/MEMORY_DOCTRINE.md`:
**storage is not memory — memory is retrieval + enforcement.**
Forgetting is a structural failure, never a personal one.
