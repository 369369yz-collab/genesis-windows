# nexus_world/ — NEXUS world code, embedded (presence + importability)

Vendored 2026-10-21 (GENESIS embed step 7, Phase 3; package completed
in the same day's pre-push fix pass) from
`~/workspace/content_team/nexus/` — the complete NEXUS package:
7 modules, the package `__init__.py`, and the `NEXUS_LAWS.json`
registry, byte-for-byte verbatim (see `PROVENANCE.md` for per-file
md5, and for what was deliberately not vendored — the source's
runtime `state/` and world-side working documents).

## Status: DESIGN / SPEC — not a live fabric

Per YZ's three-worlds sequencing (369 completes first; NEXUS is
design/spec for now; the live tailnet fabric comes later), this code is
**embedded for presence and importability only**. Nothing in the app
imports it at runtime, no NEXUS process is started, and no claim of a
live NEXUS world is made anywhere. The NEXUS *laws data* the app does
serve lives in `brain/world_data/nexus_laws.json` (Phase 2).

## Import smoke — measured 2026-10-21, honest results

Method: each module imported in a fresh interpreter with the vendored
tree loaded under its true package name — an importlib spec for the
package `nexus` with `submodule_search_locations` pointing at this
directory, exactly the layout the modules were written against in the
world tree (`from nexus import ...`).

| Module | Import as `nexus.<module>` | Result |
|---|---|---|
| `ledger.py` | OK | package init re-exports its `append`/`verify_chain` |
| `nexus_laws.py` | OK | |
| `connection_graph.py` | OK | |
| `gates.py` | OK | |
| `reflection.py` | FAIL | `from quantum.quantum_gates import network_precondition` → `ModuleNotFoundError: No module named 'quantum'` |
| `threshold.py` | FAIL | `from quantum.quantum_gates import network_precondition` → `ModuleNotFoundError: No module named 'quantum'` |
| `womb.py` | FAIL | `from quantum.quantum_gates import network_precondition` → `ModuleNotFoundError: No module named 'quantum'` |

**4 of 7 import cleanly** (before the package init was vendored:
0 of 7). The package `__init__.py` itself imports and exposes its
contract (`AGENT_SEAT`, the fail-closed exception set, ledger
re-exports).

The three blocked modules import the WORLD's `quantum` package
(`content_team/quantum/quantum_gates.py`, home of
`network_precondition()`) at top level. That package is deliberately
**not** vendored and **not** faked: the app's own seed layer is
`brain/quantum/` — a different, minimal package (qrng / seed_seal /
audit / seed_hub) that is not the world's gate layer and is not
importable under the bare name `quantum` from here. Giving the three
modules their precondition means a deliberate future step when the
NEXUS phase of the three-worlds sequence actually opens.

Two honest caveats about the four that DO import:

1. They still carry *lazy* `from quantum.quantum_gates import
   network_precondition` imports inside functions (the hard rule that
   every public entry point calls the precondition first). Importing
   is not calling: invoking their entry points in this tree would
   fail on those lazy imports. Nothing in the app calls them.
2. `gates.py` resolves its state files under a `state/` dir beside
   the modules. No such dir is vendored (it is runtime state, not
   source) and importing creates nothing.

The test suite records all of this exactly — real passes for the
four, documented skips for the three, a hard failure on any change
(`brain/tests/test_nexus_world.py`).
