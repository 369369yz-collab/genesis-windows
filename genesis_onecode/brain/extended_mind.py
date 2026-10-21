"""extended_mind.py — ADAPTER: guarded bridge from the ONE-CODE local mind
to the 369-world agent mesh (the 14 world modules).

Embed note (Phase 3, 2026-10-21): the modules were originally consumed
in place from content_team/genesis_windows/modules/ under the
adapter-not-rewrite law. YZ's embed law (2026-10-16: the whole 369
world lives inside GENESIS) superseded that for the shipped app — the
14 modules are now ALSO vendored verbatim into genesis_onecode/
world_modules/ (see world_modules/PROVENANCE.md), because the VM path
does not exist on YZ's PC. This adapter still only CONSUMES them at
runtime (guarded importlib loads, never modified). Default resolution:
  (a) explicit modules_dir argument,
  (b) env GENESIS_WORLD_MODULES,
  (c) the vendored genesis_onecode/world_modules/ inside the app,
  (d) the legacy VM path (keeps VM-side development working).

Every import is guarded (importlib); if the world code is absent or a module
fails to load, this adapter NEVER raises — it returns an explicit degraded
result instead. A degraded result is honest data, not an exception.

Call routing:
  - If genesis_onecode/veins/guarded_call.py exists and exposes the
    GuardedCall contract class (guarded_call(service, payload, timeout=3s),
    ONLINE/DEGRADED/OFFLINE, circuit breaker 5 fails -> 15 min open),
    call_module() routes through it with a LOCAL transport (the live
    tailnet fabric comes later per YZ order; the contract still owns
    timeout, breaker, and degraded shapes).
  - Otherwise (veins interfaces not built yet) it falls back to a local
    direct call with the SAME 3s timeout, and the result carries
    "degraded": True and "route": "local-fallback" so no caller can mistake
    it for a veins-routed call.

Module call convention: each module dir carries manifest.json
{name, entry (facade file), factory (class name)}. The facade class is
instantiated with no args; payload is delivered to the first available of
handle(payload) / call(payload) / __call__(payload). If none exists the
result is degraded with reason "no-entrypoint".

Technical English. Zero spend. Part of the GENESIS ONE-CODE tree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE_ROOT = os.path.dirname(_HERE)
_DEFAULT_MODULES_DIR = os.path.expanduser(
    "~/workspace/content_team/genesis_windows/modules")
_VENDORED_MODULES_DIR = os.path.join(_ONECODE_ROOT, "world_modules")


def _resolve_modules_dir(explicit: str | None = None) -> str:
    """Where the 14 world modules live, in precedence order.

    (a) an explicit constructor argument always wins;
    (b) env GENESIS_WORLD_MODULES (ops override);
    (c) the vendored copy inside the app (genesis_onecode/world_modules)
        — the only one of these that exists on YZ's PC;
    (d) the legacy VM path, so VM-side development against the live
        world tree keeps working when no vendored copy is present.
    """
    if explicit:
        return explicit
    env = os.environ.get("GENESIS_WORLD_MODULES")
    if env:
        return env
    if os.path.isdir(_VENDORED_MODULES_DIR):
        return _VENDORED_MODULES_DIR
    return _DEFAULT_MODULES_DIR

# Verified 2026-10-14: the 14 live module directories in genesis_windows/.
MODULE_NAMES = (
    "genesis-cloudburst",
    "genesis-ear",
    "genesis-eyes",
    "genesis-habits",
    "genesis-hands",
    "genesis-lab",
    "genesis-memory",
    "genesis-report",
    "genesis-scheduler",
    "genesis-station",
    "genesis-tempemail",
    "genesis-voice",
    "genesis-wakeword",
    "self-sim",
)

CALL_TIMEOUT_S = 3.0


def _try_veins_guarded_call():
    """Return a veins GuardedCall instance if the veins interface exists.

    Loads genesis_onecode/veins as a REAL package (its modules use relative
    imports, so a bare spec_from_file_location would break them). Pure
    defensive import: missing package, failed dependency import
    (veins.proto pulls genesis_final.nexus.proto), or any other error ->
    None, and the caller takes the local-fallback route. The contract is
    consumed, never re-implemented.
    """
    veins_dir = os.path.join(_ONECODE_ROOT, "veins")
    init = os.path.join(veins_dir, "__init__.py")
    if not os.path.isfile(init):
        return None
    try:
        ws = os.path.expanduser("~/workspace")
        if ws not in sys.path:
            sys.path.insert(0, ws)
        pkg_name = "onecode_veins"
        pkg = sys.modules.get(pkg_name)
        if pkg is None:
            spec = importlib.util.spec_from_file_location(
                pkg_name, init, submodule_search_locations=[veins_dir])
            pkg = importlib.util.module_from_spec(spec)
            sys.modules[pkg_name] = pkg
            spec.loader.exec_module(pkg)
        cls = getattr(pkg, "GuardedCall", None)
        if not callable(cls):
            return None
        inst = cls()
        return inst if callable(getattr(inst, "call", None)) else None
    except Exception:
        return None


class ExtendedMind:
    """Guarded adapter to the 14 genesis_windows world modules."""

    def __init__(self, modules_dir: str | None = None):
        self.modules_dir = _resolve_modules_dir(modules_dir)
        self._registry: dict[str, dict] = {}
        self._veins_call = _try_veins_guarded_call()
        self.route = ("veins-guarded" if self._veins_call
                      else "local-fallback")

    # ------------------------------------------------------------- loading
    def _manifest(self, name: str) -> dict | None:
        path = os.path.join(self.modules_dir, name, "manifest.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def load_module(self, name: str) -> dict:
        """Guarded load of one module. Never raises; returns a status dict."""
        if name in self._registry:
            return self._registry[name]
        status: dict = {"name": name, "loaded": False, "degraded": True,
                        "instance": None, "error": None, "manifest": None}
        manifest = self._manifest(name)
        if manifest is None:
            status["error"] = "manifest.json missing or unreadable"
            self._registry[name] = status
            return status
        entry = manifest.get("entry")
        factory = manifest.get("factory")
        if not entry or not factory:
            status["error"] = "manifest lacks entry/factory"
            status["manifest"] = manifest
            self._registry[name] = status
            return status
        entry_path = os.path.join(self.modules_dir, name, entry)
        if not os.path.isfile(entry_path):
            status["error"] = "entry file missing: %s" % entry
            status["manifest"] = manifest
            self._registry[name] = status
            return status
        try:
            iso = "onecode_extmind_" + name.replace("-", "_")
            spec = importlib.util.spec_from_file_location(iso, entry_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[iso] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(iso, None)
                raise
            cls = getattr(module, factory, None)
            if cls is None or not callable(cls):
                raise AttributeError(
                    "factory '%s' not found in %s" % (factory, entry))
            status["instance"] = cls()
            status["loaded"] = True
            status["degraded"] = False
            status["manifest"] = {"name": manifest.get("name"),
                                  "version": manifest.get("version")}
        except Exception as e:  # guarded: record, never raise
            status["error"] = "%s: %s" % (type(e).__name__, e)
            status["manifest"] = {"name": manifest.get("name"),
                                  "version": manifest.get("version")}
        self._registry[name] = status
        return status

    def list_modules(self) -> list[dict]:
        """Status of all 14 modules. Never raises."""
        out = []
        for name in MODULE_NAMES:
            try:
                s = self.load_module(name)
            except Exception as e:  # belt and suspenders
                s = {"name": name, "loaded": False, "degraded": True,
                     "error": "load_module raised: %s" % e}
            out.append({k: v for k, v in s.items() if k != "instance"})
        return out

    # -------------------------------------------------------------- calling
    @staticmethod
    def _deliver(instance, payload):
        for attr in ("handle", "call", "__call__"):
            fn = getattr(instance, attr, None)
            if callable(fn):
                return fn(payload)
        raise AttributeError("module exposes no handle/call entrypoint")

    def _call_with_timeout(self, fn, payload):
        """Run fn(payload) with the 3s guarded-call timeout, in a thread."""
        box: dict = {}

        def _target():
            try:
                box["result"] = fn(payload)
            except Exception as e:  # capture, never leak
                box["error"] = "%s: %s" % (type(e).__name__, e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(CALL_TIMEOUT_S)
        if t.is_alive():
            return {"ok": False, "degraded": True, "route": self.route,
                    "reason": "timeout",
                    "detail": "module call exceeded %ss" % CALL_TIMEOUT_S}
        if "error" in box:
            return {"ok": False, "degraded": True, "route": self.route,
                    "reason": "module-error", "detail": box["error"]}
        return {"ok": True,
                "degraded": self.route == "local-fallback",
                "route": self.route,
                "result": box.get("result")}

    def call_module(self, name: str, payload) -> dict:
        """Call a world module. Never raises; always returns a result dict.

        Result fields: ok, degraded, route, plus result|reason|detail.
        degraded=True whenever the call did NOT go through the veins
        guarded_call contract (veins interfaces pending) or the module
        itself is unavailable.
        """
        if name not in MODULE_NAMES:
            return {"ok": False, "degraded": True, "route": self.route,
                    "reason": "unknown-module",
                    "detail": "not one of the 14 known modules"}
        try:
            status = self.load_module(name)
        except Exception as e:
            return {"ok": False, "degraded": True, "route": self.route,
                    "reason": "load-failed", "detail": str(e)}
        if not status.get("loaded"):
            return {"ok": False, "degraded": True, "route": self.route,
                    "reason": "module-unavailable",
                    "detail": status.get("error") or "load failed"}
        instance = status["instance"]
        try:
            if self._veins_call is not None:
                # Veins contract owns timeout/breaker/degraded shapes.
                # Transport is LOCAL (live fabric comes later per YZ order).
                # GuardedCall.call requires a dict payload: wrap anything else.
                wire_payload = (payload if isinstance(payload, dict)
                                else {"payload": payload})

                def _local_transport(service, p, timeout_s):
                    return {"ok": True,
                            "result": self._deliver(instance, p)}

                vres = self._veins_call.call(
                    service=name, payload=wire_payload,
                    timeout_s=CALL_TIMEOUT_S, transport=_local_transport)
                if not isinstance(vres, dict):
                    vres = {"ok": False, "degraded": True,
                            "reason": "veins returned non-dict"}
                vres["route"] = "veins-guarded"
                return vres
            return self._call_with_timeout(
                lambda p: self._deliver(instance, p), payload)
        except Exception as e:
            return {"ok": False, "degraded": True, "route": self.route,
                    "reason": "dispatch-failed",
                    "detail": "%s: %s" % (type(e).__name__, e)}

    def status(self) -> dict:
        loaded = sum(1 for n in MODULE_NAMES
                     if self._registry.get(n, {}).get("loaded"))
        return {"route": self.route,
                "modules_known": len(MODULE_NAMES),
                "modules_loaded": loaded,
                "veins_guarded_call_available": self._veins_call is not None}


if __name__ == "__main__":
    # Smoke: list module statuses, never raises.
    em = ExtendedMind()
    print(json.dumps(em.status(), indent=1))
    for m in em.list_modules():
        print("%-18s loaded=%-5s %s" % (
            m["name"], m["loaded"], m.get("error") or "ok"))
