"""degraded_cache.py — last-known-good network state (NEXUS §3), as code.

Formula W2 / W15 (pre-birth fixes): when the fabric is cut, the local core
keeps FULL function. This cache serves the last-known-good network state —
presence snapshot + last good advisory results — with HONEST staleness
labels. Nothing in the cache is ever presented as fresh/live data:

  - get_presence() returns {"snapshot": ..., "stale": bool} or None
  - get_advisory() returns the cached result + {"cached": True, "stale": bool}
    and guarantees source: extended-mind

Adapter, not rewrite: subclasses genesis_final.nexus.cache.RelayCache —
same file format (interchangeable with the relay's cache.json), same TTL
semantics — adding:
  (a) an injectable clock so TTLs are testable without real waiting,
  (b) a unique-tmp + fsync atomic save (the never-again tmp-name law —
      the base class reuses one shared ".tmp" name),
  (c) guaranteed extended-mind advisory tagging on every advisory read.

Intended use: when guarded_call returns {"ok": False, "degraded": True},
the local core falls back to this cache instead of inventing data, and
labels everything it serves from it as cached/stale.

Stdlib only, zero spend.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Optional

import sys
_WORKSPACE = Path(__file__).resolve().parents[2]
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from genesis_final.nexus.cache import RelayCache  # noqa: E402
from genesis_final.nexus.proto import tag_advisory  # noqa: E402

from .proto import atomic_write_json  # noqa: E402

Clock = Callable[[], float]


class DegradedCache(RelayCache):
    """Last-known-good store with honest staleness labels.

    path: JSON file location. Defaults to RelayCache.cache_path().
    presence_ttl_s / advisory_ttl_s: TTLs enforced on READ, never silently.
    clock: injectable time source (seconds). Defaults to time.time.
    """

    def __init__(self, path: Path | None = None,
                 presence_ttl_s: float = 300.0,
                 advisory_ttl_s: float = 3600.0,
                 clock: Optional[Clock] = None):
        self._clock: Clock = clock or time.time
        super().__init__(path=path, presence_ttl_s=presence_ttl_s,
                         advisory_ttl_s=advisory_ttl_s)

    def _now(self) -> float:
        return self._clock()

    # -- clock-aware internals -------------------------------------------
    def _fresh(self, entry: dict, ttl_s: float) -> bool:  # noqa: N802
        # Overrides RelayCache._fresh (a staticmethod using time.time())
        # with the injectable clock. Called as self._fresh(...), so the
        # instance-method signature is compatible.
        try:
            return (self._now() - float(entry.get("stored_at", 0))) < ttl_s
        except (TypeError, ValueError):
            return False

    def _save(self, data: dict) -> None:
        # Overrides RelayCache._save: unique tmp name + fsync + os.replace
        # (the base class reuses one shared ".tmp" name — forbidden by the
        # never-again tmp-name law).
        atomic_write_json(self.path, data)

    # -- presence ----------------------------------------------------------
    def store_presence(self, snapshot: dict) -> None:
        data = self._load()
        data["presence"] = {"stored_at": self._now(), "snapshot": snapshot}
        self._save(data)

    # -- advisory results ----------------------------------------------------
    def store_advisory(self, service: str, payload_key: str,
                       result: dict) -> None:
        data = self._load()
        advisories = data.setdefault("advisories", {})
        advisories["%s:%s" % (service, payload_key)] = {
            "stored_at": self._now(), "result": result}
        self._save(data)

    def get_advisory(self, service: str, payload_key: str) -> dict | None:
        """Cached advisory, honestly labeled (cached + stale), and ALWAYS
        tagged source: extended-mind — a cached advisory is extended-mind
        advice, never local-core truth."""
        entry = self._load().get("advisories", {}).get(
            "%s:%s" % (service, payload_key))
        if not entry:
            return None
        result = dict(entry.get("result") or {})
        result["cached"] = True
        result["stale"] = not self._fresh(entry, self.advisory_ttl_s)
        return tag_advisory(result)

    def get_presence(self) -> dict | None:
        # Inherited from RelayCache; _fresh is clock-aware via the override.
        return super().get_presence()

    # -- degraded-mode helpers -------------------------------------------------
    def fallback_advisory(self, service: str, payload_key: str) -> dict | None:
        """Explicit degraded-mode read: same as get_advisory(), named for
        the call site that runs when guarded_call reports degraded."""
        return self.get_advisory(service, payload_key)

    def has_presence(self) -> bool:
        return self.get_presence() is not None
