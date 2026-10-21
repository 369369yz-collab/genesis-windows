# genesis-lab — SOFTWARE LAB (v1.0.1)

## What it does
The software lab installs a candidate application inside an isolated sandbox,
runs a structured test plan against it, and produces a PASS / FAIL / WARN
verdict with evidence, plus a Markdown report father can read.

- `install_in_sandbox(installer_path, ...)` — isolated install; records the
  installer SHA-256 and the install outcome in SQLite.
- `run_tests(app_id, test_plan, ...)` — executes test steps
  (`command` / `file_exists` / `http_ok`) and records per-step evidence.
- `verdict(app_id)` — computes PASS/FAIL/WARN from the latest run.
- `report(app_id, lang="en"|"fa")` — Markdown verdict report (English or Persian).

## Architecture
```
lab.py
  RealSandboxBackend   -> genesis-hands run_isolated (Windows Sandbox)
  MockSandboxBackend   -> DEV/TEST ONLY simulation, always marked dev_only
  SQLite state         -> lab_state.db (installs, test_runs, test_results)
  _log_event()         -> best-effort hook into genesis-report (optional)
```
Sandbox execution is delegated to the genesis-hands sandbox path
(`genesis_hands.run_isolated`, contract section 1). The lookup order is:
installed `genesis_hands` package, then the sibling `_staging/genesis-hands`
builder directory.

Verdict rules (fail-closed):
- no test data -> WARN
- any failed test -> FAIL
- all passed in a REAL sandbox -> PASS
- all passed on a dev host -> WARN (provisional; never a clean PASS)

## Bridge call points
This module makes no direct network-mind calls. Its bridge-adjacent points are:
1. **genesis-hands `run_isolated`** — the sandbox execution path (integration
   defined in `_load_hands_sandbox()`; genesis-hands is not built yet, so the
   real path currently raises an honest `SandboxUnavailableError`).
2. **`genesis_report.log_event`** (optional) — lab calls it after installs and
   test runs when the module is importable; silently skipped otherwise.

## What's real vs what's stub
- REAL: test execution engine (subprocess/file/http via stdlib), SQLite
  persistence, verdict computation, Markdown report rendering, SHA-256
  recording, input validation, the `http_ok` step (real urllib request).
- STUB / INTEGRATION POINT: the real sandbox path delegates to genesis-hands,
  which does not exist yet — documented, raises honestly, never faked.
- DEV-ONLY: `MockSandboxBackend` simulates the sandbox on the host for tests;
  its results are recorded with `dev_only=1` and can never produce a clean PASS.

## Windows-only notes
- `RealSandboxBackend` requires Windows 10/11 Pro/Enterprise (Windows Sandbox)
  AND an available genesis-hands `run_isolated`.
- On other platforms the default backend raises `SandboxUnavailableError`;
  `install_in_sandbox` returns `{"status": "sandbox_unavailable"}` instead of
  faking an install.
- `windows_smoke_test.py` runs the real checks on the Windows runner and
  exits with an honest SKIP on other platforms.

## UI surface (avatar-first)
This module builds no panels. Its UI surface is verdict cards (PASS/FAIL/WARN)
that bloom beside the avatar when a lab run completes. The full surface
contract (what shows, when, which actions) is in `UI_SURFACE_CONTRACT.md`;
rendering belongs to the avatar host's summoned-layer renderer.

## API reference
All functions return plain dicts with a `"status"` key, except `report()`
which returns a Markdown string.

| Function | Signature | Returns |
|---|---|---|
| install_in_sandbox | `(installer_path, app_id=None, install_args=None, backend=None)` | `installed` / `failed` / `sandbox_unavailable` |
| run_tests | `(app_id, test_plan, backend=None)` | `completed` (+ passed/failed/results) or `error` |
| verdict | `(app_id)` | `ok` + `verdict` PASS/FAIL/WARN + evidence, or `error` |
| report | `(app_id, lang="en")` | Markdown string |

Test plan step kinds: `command` {command:[...], timeout_s}, `file_exists`
{path}, `http_ok` {url, timeout_s}.

Data dir: `GENESIS_LAB_DATA_DIR` env var, else `~/.genesis/lab`.
