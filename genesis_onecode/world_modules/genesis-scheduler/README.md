# genesis-scheduler — SCHEDULED TASKS (v1.0.0)

## What it does
Schedules jobs that fire automatically on father's Windows machine.

- `schedule(name, trigger, action, overwrite=False)` — create a job.
- `unschedule(name)` — delete a job.
- `list_jobs()` — list jobs with backend info.
- `morning_news(time_str="07:00")` — recipe: daily headline digest.
- `reminder(name, time_str, message)` — recipe: daily popup reminder.

Trigger shapes: `{"type":"daily","time":"HH:MM"}`,
`{"type":"weekly","days":["mon","wed"],"time":"HH:MM"}`,
`{"type":"once","at":"YYYY-MM-DDTHH:MM"}`,
`{"type":"interval","minutes":N}`.
Action shapes: `{"kind":"command","command":[...]}` or
`{"kind":"message","title":..,"text":..}`.

## Architecture
```
scheduler.py
  SchtasksBackend  -> wraps schtasks.exe (Windows production)
  DevBackend       -> JSON store (jobs.json), non-Windows, dev_only
recipes/
  morning_news.py  -> real RSS fetch (urllib) -> dated digest .md
  reminder.py      -> Windows auto-dismissing toast (WScript.Shell.Popup 20s,
                    MessageBoxW fallback); always logs to reminders.log
```
Backend selection is automatic: Windows -> schtasks, elsewhere -> dev store.
All public functions validate name/trigger/action first and raise
`SchedulerError` on invalid input (fail-closed).

## Bridge call points
None. The scheduler performs no network-mind calls. The `morning_news`
runner performs a plain public-RSS HTTP fetch (stdlib urllib) at fire time —
a real fetch, never fabricated headlines; on failure it exits 1 and writes an
honest error file.

## What's real vs what's stub
- REAL: trigger/action validation, schtasks command construction and
  execution on Windows, job listing via `schtasks /Query`, both recipe runner
  scripts (real RSS parse, real MessageBoxW, real file logging).
- DEV-ONLY: `DevBackend` stores jobs in JSON on non-Windows hosts. Jobs are
  marked `dev_only=True` and the docs/state say plainly they will NOT fire
  until created on Windows. Nothing here pretends a dev-stored job runs.
- Not faked anywhere: on Linux `SchtasksBackend()` raises `SchedulerError`
  with an honest message instead of silently using the dev store.

## Windows-only notes
- Production scheduling requires Windows + `schtasks.exe` on PATH.
- **Namespacing:** every GENESIS job is created as `\GENESIS\<name>` in the
  Task Scheduler folder tree, so a bare name can never collide with an OS or
  third-party task. `unschedule`/`list_jobs` use the same namespace, and
  `list_jobs` only returns `\GENESIS\` tasks.
- **Overwrite guard:** `schedule(..., overwrite=False)` (the default) never
  replaces an existing job. Sequentially, a pre-query
  `schtasks /Query /TN \GENESIS\<name>` returns `already_exists` without
  issuing a create. Concurrently, the create is issued WITHOUT `/F`, so if
  another caller wins the name first, schtasks itself rejects the duplicate
  create and the module maps that failure to `already_exists` — exactly one
  concurrent schedule wins, the rest get `already_exists`, no silent
  replace. `overwrite=True` is the ONLY path that passes `/F` (deliberate
  replace).
- **`/TR` quoting:** built with `subprocess.list2cmdline` (MSVC command-line
  rules — the parsing python.exe and every C-runtime program applies to the
  CreateProcess command line Task Scheduler launches). Quoted lines were
  verified to parse back to the exact argv, including embedded quotes,
  backslashes, and `%` signs. `%` passes through VERBATIM on purpose:
  CreateProcess performs no `%VAR%` expansion, so doubling `%` would corrupt
  argv (a reminder "50% off" would arrive as "50%% off"). Residual risk,
  stated honestly: if a command action routes through `cmd.exe` itself
  (e.g. `["cmd", "/c", ...]`), cmd WILL expand `%VAR%` at task time — that
  is cmd's documented behavior; double the `%` yourself in that case.
- **`once` trigger date:** `/SD` is emitted as `MM/DD/YYYY` because schtasks
  parses the date per the machine locale — this requires a US-locale date
  order on the Windows host. The returned dict carries a `date_format_note`
  saying so. On non-US Windows, set the region date format to M/d/yyyy or
  the one-shot task may land on the wrong date.
- `message` actions resolve to the bundled `recipes/reminder.py` invocation,
  which shows a small auto-dismissing (20s) Windows toast; see
  `UI_SURFACE.md` for the UI-surface contract (no panels, avatar-first law).
- `windows_smoke_test.py` creates/lists/deletes a real schtasks job on the
  Windows runner; on other platforms it exits with an honest SKIP.

## API reference
All functions return plain dicts with a `"status"` key.

| Function | Notes |
|---|---|
| schedule(name, trigger, action, overwrite=False) | `scheduled` (Windows) / `scheduled_dev` (dev) / `already_exists` / raises `SchedulerError` |
| unschedule(name) | `unscheduled` / `not_found` / `error` |
| list_jobs() | `ok` + `backend` (`"schtasks"`/`"dev"`) + `jobs` |
| morning_news(time_str="07:00", name="morning_news") | daily digest job; recipe script at `recipes/morning_news.py` |
| reminder(name, time_str, message) | daily message job; runner at `recipes/reminder.py` |

Data dir: `GENESIS_SCHEDULER_DATA_DIR` env var, else `~/.genesis/scheduler`.
Job names: `^[A-Za-z0-9][A-Za-z0-9 _\-]{0,63}$`. Times: `HH:MM` 24-hour.
