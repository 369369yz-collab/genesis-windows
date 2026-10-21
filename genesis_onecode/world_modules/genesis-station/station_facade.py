"""station_facade.py — loader adapter for the function-based genesis-station module.

ModuleManager.call_guarded() constructs the factory with no arguments and
calls methods on the shared instance. This thin adapter exposes the
module's public function API through a zero-arg-constructible class;
attribute access delegates to the underlying module. No logic lives here.
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


_impl = _load("station", "station.py")


class StationModule:
    """Adapter over genesis-station 1.0.0 (function API)."""

    def __init__(self):
        self._impl = _impl

    def __getattr__(self, name):
        return getattr(self._impl, name)

    def health_check(self):
        return {"ok": True, "module": "genesis-station", "version": "1.0.0"}
