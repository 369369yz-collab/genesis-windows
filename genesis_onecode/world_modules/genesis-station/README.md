# genesis-station — 369 PRODUCTION STATION

## What it does

A local, persistent job queue for production work on the GENESIS Windows PC.
It accepts production jobs, runs them with a worker, and keeps their full
history in SQLite so nothing is lost across restarts.

Two job kinds:

- **render** — executes a caller-supplied `ffmpeg` command line (bounded,
  list-form, no shell) and records the output artifact.
- **produce** — executes the documented production pipeline: a declarative
  list of steps (`mkdir`, `write_file`, `copy_file`, `ffmpeg`, `zip`) run
  inside a job work directory, with per-step results recorded.

Public API:

| Function | Returns |
|---|---|
| `submit_job(job: dict) -> str` | new job id |
| `job_status(job_id: str) -> dict` | `{"status": "ok", ...}` or `{"status": "not_found"}` |
| `cancel_job(job_id: str) -> dict` | `{"status": "ok", ...}`, `{"status": "not_cancellable", ...}` or `{"status": "not_found"}` |
| `probe_hardware() -> dict` | live hardware report (see below) |
| `process_next_job(db_path=None) -> dict` | runs one pending job synchronously |
| `start_worker(stop_event, db_path=None, poll_s=2.0)` | daemon worker thread |

Job dict schema:

```python
{
    "kind": "render" | "produce",   # required
    "name": "human readable name",  # required, non-empty
    "priority": 0,                  # optional int, higher runs first
    "params": { ... },              # required, kind-specific
}
```

Render params:

```python
{
    "ffmpeg_args": ["-y", "-i", "in.mp4", "out.mp4"],  # after the ffmpeg binary
    "output": "out.mp4",        # relative; MUST stay inside workdir
    "workdir": "C:/jobs/job1",  # created if missing
    "timeout_s": 3600,          # optional
    "duration_s": 120.5,        # optional; enables progress reporting
}
```

Produce params:

```python
{
    "workdir": "C:/jobs/job1",
    "timeout_s": 3600,          # optional, applies to ffmpeg steps
    "steps": [
        {"op": "mkdir",      "params": {"path": "assets"}},
        {"op": "write_file", "params": {"path": "assets/note.txt",
                                        "content": "text"}},
        {"op": "copy_file",  "params": {"src": "staging/a.png",
                                        "dst": "assets/a.png"}},
        # copy_file src MUST live inside the workdir (workdir-relative);
        # absolute paths outside the workdir are rejected.
        {"op": "ffmpeg",     "params": {"ffmpeg_args": [...],
                                        "output": "clip.mp4"}},
        {"op": "zip",        "params": {"sources": ["assets/note.txt"],
                                        "output": "bundle.zip"}},
    ],
}
```

`submit_job` validates everything up front and raises `ValueError` on bad
input (unknown kind/op, missing fields, path escaping the workdir).

## Architecture

```
submit_job() ──validate──▶ SQLite jobs table (pending)
                                │
worker: process_next_job() / start_worker() thread
                                │  highest priority first, then oldest
                          ┌─────┴──────┐
                       render        produce
                    (ffmpeg Popen,   (step runner,
                     stderr-drained,  paths confined
                     killable)       to workdir)
                                │
                          done / failed / cancelled  (all recorded)
```

- Queue storage: SQLite (`jobs` table), one row per job with state machine
  `pending → running → done | failed | cancelled`.
- DB location: `%LOCALAPPDATA%\GENESIS\station\jobs.db` on Windows,
  `~/.genesis/station/jobs.db` elsewhere; `GENESIS_STATION_DB` env overrides.
- ffmpeg runs with `Popen` in list form — **no shell** — with a dedicated
  stderr-drain thread (ffmpeg writes progress to stderr; an undrained pipe
  would stall long encodes). Progress is parsed from `time=` stamps when
  `duration_s` is provided.
- Path safety: every job-relative path is resolved and must stay inside the
  job workdir (`_confine`); escapes raise `ValueError`.
- Cancellation: pending jobs cancel instantly. Running jobs are signalled
  via an in-process event (ffmpeg is terminated). Running-job cancellation
  works only when the worker runs in the same process — the supported
  deployment.

## Bridge call points

**None.** This module never contacts the network mind and makes zero network
calls. It is pure local execution, confined in two layers: (1) ffmpeg args
are content-validated at submit time AND re-validated at run time — absolute
paths (any platform), ".." segments, and local-access / network URL schemes
(file:, pipe:, http:, ipfs:, ...) are rejected even when embedded in
option/filter values ("movie=/abs/x.mp4", "subtitles=http://host/x.srt"),
checked after ffmpeg's own double backslash-unescape; the concat demuxer
requires exactly one "-safe 1"; tee-muxer branch outputs are each confined;
device/capture formats are rejected; callers cannot override
-protocol_whitelist; and indirect files ffmpeg reads (filter scripts,
playlists/manifests, concat lists) have their contents validated and
confined; (2) every ffmpeg invocation is locked to "-protocol_whitelist
file,pipe,lavfi", so ffmpeg itself refuses any non-whitelisted protocol.
Residual risks (symlink indirection, pre-existing workdir contents) are
documented in BUILDER_NOTES.md, not stamped away. (If a future "remote
render farm" exists, that would be a new module, not a silent addition here.)

## What's real vs what's stub

| Area | Status |
|---|---|
| SQLite queue, validation, priority ordering | REAL — tested |
| ffmpeg render execution (list-form, timeout, cancel, stderr tail on failure) | REAL — tested with real encodes |
| produce pipeline (mkdir/write/copy/ffmpeg/zip) | REAL — tested |
| Path-escape protection | REAL — tested |
| `probe_hardware()` | REAL live OS queries; see honesty note |
| GPU encode acceleration (`-hwaccel`) | NOT claimed — caller passes their own ffmpeg args |
| Remote/distributed workers | NOT implemented — single-machine queue only |
| Network calls | NONE — enforced in two layers: content validation of ffmpeg_args (absolute paths, "..", URL/protocol schemes incl. embedded in filter values, at submit + run time) AND ffmpeg-level `-protocol_whitelist file,pipe,lavfi` on every invocation |

**Honesty note on `probe_hardware()`:** it reports only what the OS exposes
at call time. CPU brand via `wmic` (Windows) / `/proc/cpuinfo` (Linux);
memory via `GlobalMemoryStatusEx` (Windows) / `/proc/meminfo` (Linux); GPU
via `nvidia-smi` and (Windows) `wmic win32_VideoController`. Anything
undetectable is reported as `"unknown"` / `null` with its source named —
never guessed, never padded. On this Linux dev VM it correctly reports
`gpu.detected: false` because no GPU is present.

## Windows-only notes

- Developed and tested on Linux; Windows-only branches (`wmic` probing,
  `LOCALAPPDATA` paths, `GlobalMemoryStatusEx`) are platform-guarded and
  were **not** executed here. `windows_smoke_test.py` exercises them on the
  Windows runner.
- Runtime requirement on Windows: an `ffmpeg` binary on `PATH`
  (e.g. via `winget install Gyan.FFmpeg`); without it, render jobs fail
  honestly with "ffmpeg executable not found on PATH".

## API reference

See module docstring in `station.py`. State values: `pending`, `running`,
`done`, `failed`, `cancelled`. Status dicts always carry a `"status"` key
(`"ok"`, `"not_found"`, `"not_cancellable"`, `"idle"`, `"error"` context).
