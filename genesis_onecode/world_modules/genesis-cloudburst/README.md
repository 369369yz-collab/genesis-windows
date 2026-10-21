# genesis-cloudburst — honest manual-offload handoff for GPU work

## What it does

Decides whether a heavy job (typically a GPU-flagged `render`) may leave the
local PC, and — when allowed — prepares an **honest manual handoff** for a
free-tier GPU session instead of pretending to submit it automatically.

Public API:

| Function | Returns |
|---|---|
| `can_offload(job: dict) -> bool` | policy gate (True/False) |
| `offload(job: dict) -> dict` | `{"status": "manual_handoff", ...}` or `{"status": "rejected", "reason": ...}` |
| `fetch_result(offload_id: str) -> dict` | `{"status": "pending"/"ok"/"unknown", ...}` |
| `ingest_result(offload_id, result_path) -> dict` | registers a manually produced result file |
| `init_config(path=None) -> dict` | writes the local config template (never overwrites) |
| `list_providers() -> dict` | documented free-tier provider catalog |
| `config_path() -> str` | resolved local config path |

Job shape for `can_offload`/`offload`:

```python
{"kind": "render" | "produce", "name": "...",
 "params": {"gpu": True, ...}}   # gpu=True REQUIRED; local_only=True vetoes
```

A typical handoff:

```python
import cloudburst
cloudburst.init_config()          # once; edit the file it creates
if cloudburst.can_offload(job):
    h = cloudburst.offload(job)   # -> manual_handoff with next_steps
    # ... father runs the free-tier session manually in his browser ...
    cloudburst.ingest_result(h["offload_id"], r"C:\results\out.mp4")
    print(cloudburst.fetch_result(h["offload_id"]))
```

## Architecture

```
can_offload(job) ──policy──▶ config present? enabled? provider known?
                             job gpu-flagged? not local_only?
        │
        ▼ True
offload(job) ──▶ local SQLite ledger (awaiting_manual_run)
                 + {"status": "manual_handoff", "next_steps": [...]}
        │
        ▼ (manual, in the father's browser — OUTSIDE this module)
ingest_result(offload_id, result_path) ──▶ ledger → done
```

- Config: local JSON only (`%LOCALAPPDATA%\GENESIS\cloudburst\` on Windows,
  `~/.genesis/cloudburst/` elsewhere; `GENESIS_CLOUDBURST_CONFIG` overrides).
  **Never committed to the repo.** `init_config()` writes a template with
  `offload_enabled: false` (safe default).
- Ledger: SQLite `ledger.db` next to the config; every handoff and every
  ingested result is recorded with UTC timestamps.

## Bridge call points

**None.** This module never contacts the network mind and makes **zero
network calls** — a test (`test_offload_makes_zero_network_calls`) fails the
suite if any socket is ever created. The actual GPU run happens manually by
the father in his own browser session.

## Quota reality (read before relying on free tiers)

Free-tier GPU is **limited, variable, and carries no SLA**:

- **Google Colab (free):** limited free GPU availability that varies with
  demand; limits change without notice; sessions disconnect on idle timeout
  and have a maximum lifetime. Verify the live limits in Google's own Colab docs.
- **Kaggle (free):** a limited weekly GPU quota that Kaggle adjusts over
  time; not guaranteed; account required (phone verification may apply);
  notebooks time out. Verify the live quota in Kaggle's own docs.

This module **never promises unlimited quotas** — `list_providers()` states
the reality qualitatively on purpose, and every handoff repeats the
`quota_notice`. Treat free tiers as "best effort, may be unavailable".

## Zero-spend & Terms-of-Service position

- No money is spent, no paid API is called, no credentials are stored in the
  repo. The config holds only convenience bookmark URLs, never secrets.
- **Automated submission is deliberately NOT implemented.** Free-tier
  notebook providers prohibit bot/automated access in their Terms of Service;
  automating against them risks account bans for the father. `offload()`
  records the intent locally and hands the father numbered manual steps.
  This is a design decision, not a missing feature.

## What's real vs what's stub

| Area | Status |
|---|---|
| Policy gate (`can_offload`) | REAL — tested, incl. all veto paths |
| Config template + safe defaults + 0600 perms | REAL — tested |
| Manual handoff package (steps, quota + ToS notices) | REAL — tested |
| Ledger: track handoff → ingest result → fetch state | REAL, persistent — tested |
| Zero-network guarantee | REAL — enforced by a failing-if-socket test |
| Provider catalog | DOCUMENTED static data (honest, qualitative quotas) |
| Automatic job submission to Colab/Kaggle | INTENTIONALLY ABSENT (ToS) — never to be "completed" silently |
| Quota availability checks | NOT POSSIBLE from here — never claimed |

## Windows-only notes

- No Windows-only APIs are used; the module is cross-platform. On Windows
  the config/ledger live under `%LOCALAPPDATA%\GENESIS\cloudburst\`.
- `windows_smoke_test.py` exercises config creation, policy gating, a full
  handoff→ingest cycle, and the zero-network property on the Windows runner.

## API reference

See module docstring in `cloudburst.py`. All dict-returning functions carry a
`"status"` key: `"ok"`, `"exists"`, `"rejected"`, `"manual_handoff"`,
`"pending"`, `"unknown"`, `"error"`. `can_offload` returns a plain bool.
