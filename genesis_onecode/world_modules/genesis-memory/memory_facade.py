"""memory_facade.py — loader adapter for the function-based genesis-memory module.

Exposes memory.py's function API on the instance and the sync companion
module as the `sync` attribute. See FACADE pattern in cloudburst_facade.py.
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(iso_name, filename):
    # Register in sys.modules BEFORE exec: decorators like @dataclass
    # resolve sys.modules[cls.__module__] at class-creation time.
    iso = "genesis_bundle_" + iso_name
    spec = importlib.util.spec_from_file_location(
        iso, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[iso] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(iso, None)
        raise
    return module


_impl = _load("memory", "memory.py")
_sync_impl = _load("memory_sync", "sync.py")

# never-forget memory (YZ order 2026-10-13): the extracted GENESIS must never
# forget either — open loops + gate live inside this module, pure stdlib.
sys.path.insert(0, _HERE)
try:
    import never_forget as _nf_impl
    _never_forget = _nf_impl
except Exception:
    _never_forget = None
finally:
    sys.path.remove(_HERE)


class MemoryModule:
    """Adapter over genesis-memory 1.0.0 (function API + sync companion)."""

    def __init__(self):
        self._impl = _impl
        self.sync = _sync_impl
        self.never_forget = _never_forget

    def __getattr__(self, name):
        return getattr(self._impl, name)

    def health_check(self):
        return {"ok": True, "module": "genesis-memory", "version": "1.0.0"}
