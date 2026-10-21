# genesis-selfsim — GENESIS Self-Simulation Module

Two twins, one fidelity loop. The program simulates itself: GENESIS carries
a live internal model of who she is (Twin A) and an exact mirror of the
environment she runs in (Twin B), and a loop keeps proving the two agree
with each other and with reality.

## Files

| File | Role |
|---|---|
| `self_model.py` | Twin A entry + `SelfSimulation` factory. Loads her identity from sealed assets fail-closed; exposes `identity()`, `presentation_state()`, `reflect(question)`. |
| `environment_model.py` | Twin B. Introspects the live runtime (module registry, launcher checks, voice, avatar, permission gates, bridge, OS facts); exposes `snapshot()`, `diff_vs_reality()`. |
| `simulation_loop.py` | The fidelity loop. `fidelity_report()` -> `{self_ok, env_ok, drift[]}`. |

## Contract

```python
mgr = ModuleManager("modules"); mgr.scan()
mod = mgr.load("genesis-selfsim")          # None = quarantined (fail-closed)
report = mgr.call_guarded("genesis-selfsim", "fidelity_report")
# report["result"] == {"self_ok": bool, "env_ok": bool, "drift": [...],
#                      "reasons": [...], "expression": ..., "checked_at": ...}
```

## Fail-closed semantics

- A sealed identity asset missing or hash-drifted -> Twin A refuses to form
  (`SelfModelError`, named reason) -> module quarantined -> launch BLOCKED.
- Any drift between Twin B and live reality -> `env_ok=False` -> launch BLOCKED.
- Drift or warning moves her expression to `solemn`; clean state is `calm`.

## Non-goals

The twin is a mirror, not a second brain: it never replaces the kernel,
never phones home with personal data, never grants itself permissions
(permission gates stay deny-by-default, father-only).
