"""hands_facade.py — loader adapter for the genesis-hands package.

The package (genesis_hands/) ships beside this file; the ModuleManager puts
the module directory on sys.path while importing the entry, so the absolute
`genesis_hands.*` imports inside the package resolve. Attribute access
delegates to the package's public API (execute, check_permission).
"""
from __future__ import annotations

import genesis_hands as _impl


class HandsModule:
    """Adapter over genesis-hands 1.0.0 (package API)."""

    def __init__(self):
        self._impl = _impl

    def __getattr__(self, name):
        return getattr(self._impl, name)

    def health_check(self):
        return {"ok": True, "module": "genesis-hands", "version": "1.0.0"}
