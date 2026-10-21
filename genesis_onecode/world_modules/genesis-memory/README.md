# genesis-memory — Personal Memory

## What it does
Local-first personal memory for GENESIS. Stores key/value facts with tags in a
SQLite database on the machine (`genesis_memory.db` next to the module files),
retrieves them with local keyword ranking, and supports an explicit,
bridge-gated sync path to the network mind. Privacy principle: **nothing
leaves the machine without an explicit bridge call** — sync.py never transmits
anything by itself.

## Architecture
- `memory.py` — CRUD + search over SQLite:
  `remember(key, value, tags=[])`, `recall(query, top_k=5)`,
  `forget(key)`, `list_tags()`. All return plain dicts with a `"status"` key.
  `remember` is an upsert. `recall` scores by substring match with an
  exact-key bonus; it is keyword search, not semantic search.
- `sync.py` — documented sync with the network mind:
  `export_manifest()` (checksummed, serializable payload — no transmission),
  `import_manifest(d, policy="newer_wins")` (validated merge into this machine;
  tampered manifests are rejected on sha256 mismatch),
  `register_bridge(callable)` / `send_to_mind(manifest)` — the bridge call
  point. Until a real bridge registers itself, `send_to_mind` returns
  `{"status": "bridge_not_configured"}` and sends nothing.

## Bridge call points
- `sync.send_to_mind(manifest)` — the ONLY exit point for memory data. Stubbed
  honestly: no registered bridge -> `bridge_not_configured`, zero network
  traffic. The bridge integration layer calls `register_bridge()` on Windows.

## What's real vs what's stub
- REAL: local store, recall ranking, manifest export/import with integrity
  check, merge policies, idempotent forget.
- STUB: the actual bridge transmission to the network mind (not implemented
  here by design; the bridge belongs to the bridge integration layer).
- NOT CLAIMED: semantic/embedding recall (keyword only), encryption at rest
  (relies on Windows disk/user-profile security; document any hardening later).

## Windows-only notes
No Windows-only APIs in this module. SQLite + stdlib run identically on
Linux (dev) and Windows 10/11 (target). The store path defaults to the module
directory — on Windows this is the installed module folder; `db_path` args
allow redirecting to e.g. `%LOCALAPPDATA%\GENESIS`.

## API reference
```python
remember(key, value, tags=[])          -> {"status":"ok","key":..,"action":"stored"|"updated"}
recall(query, top_k=5)                 -> {"status":"ok","results":[{"key","value","tags","score"}]}
forget(key)                            -> {"status":"ok","key":..,"existed":bool}
list_tags()                            -> {"status":"ok","tags":[...]}
export_manifest()                      -> {"status":"ok","manifest":{...}}
import_manifest(d, policy="newer_wins") -> {"status":"ok","imported":N,"skipped":M}
send_to_mind(manifest)                 -> {"status":"ok"|"bridge_not_configured",...}
```
