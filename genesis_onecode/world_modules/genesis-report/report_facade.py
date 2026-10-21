"""report_facade.py — loader adapter for the function-based genesis-report module.

Exposes event_log.py's function API on the instance and the daily-report
companion module as the `daily_report` attribute.
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


_impl = _load("report_event_log", "event_log.py")
_daily_impl = _load("report_daily", "daily_report.py")


class ReportModule:
    """Adapter over genesis-report 1.0.0 (function API + daily companion)."""

    def __init__(self):
        self._impl = _impl
        self.daily_report = _daily_impl

    def __getattr__(self, name):
        return getattr(self._impl, name)

    def health_check(self):
        return {"ok": True, "module": "genesis-report", "version": "1.0.0"}
