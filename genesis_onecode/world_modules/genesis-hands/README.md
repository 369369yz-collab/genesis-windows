# genesis-hands v1.0.0

The HANDS module of the GENESIS Windows assistant: the part of GENESIS that
*does* things on the Windows desktop and in a web browser.

## What it does

- **Permission gate** (`permission_gate.py`): every action is checked against
  a three-tier rule set (`permissions.json`) — `auto` (allow), `ask` (needs
  approval), `never` (always deny). Fail-closed: anything matching no rule
  returns `"ask"`, and the never tier always wins.
- **Execution engine** (`hands.py`): `execute(plan)` runs a plan
  `{"mode": "local"|"web", "steps": [...]}` step by step. Every step passes
  through the gate FIRST; a denied step aborts the whole plan. Local steps
  drive the Windows desktop via pywinauto; web steps drive a real Chromium
  browser via Playwright. Steps with `risk: "high"` are routed through
  Windows Sandbox first, when the sandbox is available.
- **Sandbox isolation** (`sandbox.py`): `run_isolated(command)` runs a command
  inside Windows Sandbox and returns its result. Windows-only, honestly
  guarded (raises `RuntimeError` on non-Windows).

## Architecture

```
genesis_hands/
  __init__.py          exports: execute, check_permission
  permission_gate.py   check(action) -> "allow"|"ask"|"deny"  (load_rules)
  hands.py             execute(plan, on_ask=None) -> dict
                       run_single_step(step) -> dict  (used by step_runner)
  step_runner.py       python -m genesis_hands.step_runner <base64-step>
                       (single gated step executor inside a sandbox)
  sandbox.py           is_available() -> bool
                       run_isolated(command, timeout_s=300.0) -> dict
  permissions.json     shipped default tier rules
```

Step schema: `{"kind", "target", "risk", "params"?}`. Action for the gate:
`{"kind": str, "target": str, "risk": "low"|"medium"|"high"}`.

Local kinds: `type_text`, `press_key`, `click`, `open_app`, `close_app`,
`run_command`. Web kinds: `goto`, `click`, `fill`, `type`, `press`, `wait`,
`screenshot`, `extract_text`.

Every public function returns a plain dict with a `"status"` key
(`"completed"|"aborted"` for plans, `"ok"|"error"` for steps and sandbox).

`execute()` accepts an optional `on_ask(action, step) -> bool` callback for
steps the gate marks `"ask"`. **Without a callback, "ask" is treated as
denied** (fail-closed) — the plan aborts rather than guessing.

## UI surface (avatar-first contract)

Per `GENESIS_UI_CONTRACT_AVATAR_FIRST.md`, this module builds **no panels**.
Its only UI surface is the **permission-ask chip**, rendered by the avatar
host's summoned-layer renderer:

- **When shown:** exactly when the gate returns `"ask"` for a step.
  `"allow"` (auto tier) and `"deny"` (never tier) show nothing.
- **What it shows:** a small floating chip beside GENESIS with the action's
  `kind`, `target`, `risk`, and — for `run_command` — the real
  `command_text` payload (the approver must see what actually executes, not
  just the target label), plus **Allow** / **Deny** actions.
- **What the actions do:** Allow → `on_ask` returns `True` (step proceeds);
  Deny → `on_ask` returns `False` (plan aborts). No answer / dismissed chip →
  treated as Deny (fail-closed). The chip blooms in softly and dismisses on
  choice; dark + gold identity.
- **Code contract:** `on_ask(action, step)` IS the chip's backend contract —
  the host calls it when the user taps Allow/Deny and routes the boolean
  back. The module never renders anything itself.

## Bridge call points

**None.** This module makes zero network calls. Plans arrive from the network
mind through the bridge *before* `execute()` is called, and results are
returned to the caller. Web automation drives a real local browser; it never
fabricates page data. The design is honest by construction: nothing here can
fake a remote answer.

## What's real vs what's stub

| Area | Status |
|---|---|
| Permission gate (3 tiers, fail-closed, never-wins) | REAL — fully implemented, 14 unit tests |
| Plan dispatch, deny/ask abort semantics | REAL — implemented, mock-tested (see below) |
| High-risk sandbox routing in `execute()` | REAL logic — routes via `run_isolated` when available; when unavailable the result honestly reports `"sandboxed": False` |
| `sandbox.run_isolated()` on Windows | IMPLEMENTED BUT NOT LIVE-TESTED — the wsb/config/payload construction is mock-tested; no Windows host was available during development (BUILDER_NOTES.md) |
| Local backend (pywinauto keyboard/mouse/app control) | IMPLEMENTED BUT NOT LIVE-TESTED — guarded, refuses honestly on non-Windows |
| Web backend (Playwright) | REAL code, tested only through mocks here — needs a real browser on the target |
| Network/LLM integration | INTENTIONALLY ABSENT — no network calls anywhere in this module |

## Windows-only notes

- `pywinauto` is installed only on Windows (`sys_platform == "win32"`
  marker in requirements.txt).
- `sandbox.run_isolated()` raises `RuntimeError` on non-Windows by design.
- After installing requirements on Windows, also run once:
  `python -m playwright install chromium` (free, no spend).
- `windows_smoke_test.py` runs on the Windows target and performs no
  destructive action.

## API reference

```python
from genesis_hands import execute, check_permission
from genesis_hands import permission_gate, sandbox

check_permission({"kind": "click", "target": "ok", "risk": "medium"})
# -> "ask"

execute({
    "mode": "web",
    "steps": [
        {"kind": "goto", "target": "https://example.com", "risk": "low"},
        {"kind": "extract_text", "target": "", "risk": "low"},
    ],
}, on_ask=lambda action, step: True)
# -> {"status": "completed", "results": [...]}

sandbox.is_available()        # -> bool
sandbox.run_isolated(["python", "--version"])  # -> {"status": "ok", ...}
```

`permission_gate.load_rules(path=None)` reloads `permissions.json`
(fail-closed: bad config raises `GateConfigError` instead of silently
allowing everything).
