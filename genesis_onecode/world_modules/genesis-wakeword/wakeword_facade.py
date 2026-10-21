"""wakeword_facade.py — loader adapter for the class-based genesis-wakeword module.

WakeWordDetector is already a zero-arg-constructible factory class; this
subclass only adds the health_check() hook the updater post-swap gate
expects (launcher.py). All behavior is inherited unchanged; the reviewed
wakeword.py ships byte-identical.
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


_base = _load("wakeword_mod", "wakeword.py")


class WakeWordDetectorModule(_base.WakeWordDetector):
    """WakeWordDetector plus the loader health_check hook."""

    def health_check(self):
        return {"ok": True, "module": "genesis-wakeword", "version": "1.0.0"}
