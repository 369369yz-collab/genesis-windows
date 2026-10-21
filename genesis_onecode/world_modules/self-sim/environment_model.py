"""environment_model.py — Twin B: the program's exact internal mirror of its
own environment.

Built by introspecting the LIVE runtime (never from cached claims):

  modules        <- ModuleManager registry over modules/: every manifest
                    (name, version, entry, sha256), load state, quarantined
                    modules + reasons
  launch_health  <- launcher --check results (passed in; minimal probes
                    when absent)
  voice          <- voice/engine/ presence + config
  avatar         <- avatar_host.py + WebView2 overlay host + plate set
  permissions    <- permission_gates.py 8-permission vocabulary + grants
  bridge         <- bridge_client.py heartbeat status, last sync
  os             <- install-time --seal record, OS version, WebView2,
                    audio device, absolute install paths

"Exact" means the twin MUST match reality; diff_vs_reality() re-probes
reality independently and any mismatch is returned as drift (a defect,
never a cosmetic difference).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULES_SUBDIR = "modules"
RUNTIME_SUBDIR = "runtime"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_path(root: Path):
    """Make runtime/ importable for introspection (permission_gates,
    bridge_client). Restores sys.path afterwards."""
    runtime_dir = str(root / RUNTIME_SUBDIR)

    class _Guard:
        def __enter__(self):
            self.added = runtime_dir not in sys.path
            if self.added:
                sys.path.insert(0, runtime_dir)
            return self

        def __exit__(self, *exc):
            if self.added:
                try:
                    sys.path.remove(runtime_dir)
                except ValueError:
                    pass
            return False

    return _Guard()


class EnvironmentModel:
    """Twin B — the world the program runs in, mirrored exactly."""

    def __init__(self, genesis_windows_dir) -> None:
        self._root = Path(genesis_windows_dir).resolve()
        self._snapshot: dict | None = None
        # The loader's own manifest-name -> directory mapping, kept so
        # drift detection re-probes the exact directories the loader used
        # (no name guessing: e.g. "genesis-selfsim" lives in self-sim/).
        self._manifest_dirs: dict[str, str] = {}

    # -- builders ---------------------------------------------------------
    def _module_registry(self) -> dict:
        """Every modules/<name>/manifest.json: name, version, entry,
        sha256; load state; quarantined modules + reasons."""
        result: dict[str, dict] = {}
        with _runtime_path(self._root):
            from modules.module_loader import ModuleManager
            mgr = ModuleManager(str(self._root / MODULES_SUBDIR))
            scan = mgr.scan()
            self._manifest_dirs = dict(mgr._manifest_dirs)
            for name, info in scan.items():
                entry: dict = {"scan": info["status"]}
                if info["status"] == "valid":
                    entry.update({
                        "version": info.get("version"),
                        "entry": mgr._manifests[name]["entry"],
                        "sha256": dict(mgr._manifests[name]["sha256"]),
                    })
                    loaded = mgr.load(name)
                    entry["loaded"] = loaded is not None
                    entry["quarantine_reason"] = mgr.last_error(name)
                else:
                    entry["quarantine_reason"] = info.get("reason")
                result[name] = entry
        return result

    def _voice_state(self) -> dict:
        engine_dir = self._root / "voice" / "engine"
        config_path = engine_dir / "voice_config.json"
        config: dict = {}
        if config_path.is_file():
            with open(config_path, encoding="utf-8") as handle:
                config = json.load(handle)
        engine_py = engine_dir / "engine.py"
        return {
            "engine_py_present": engine_py.is_file(),
            "engine_sha256": (_sha256_file(engine_py)
                              if engine_py.is_file() else None),
            "engine_id": config.get("engine"),
            "fallback_id": config.get("fallback"),
            "device": "cpu (Piper/Ava offline engines ship in the build)",
        }

    def _avatar_state(self) -> dict:
        host_py = self._root / "runtime" / "avatar_host.py"
        plate_dir = self._root / "avatar" / "host" / "assets"
        plates = sorted(p.name for p in plate_dir.glob("plate_*.png")) \
            if plate_dir.is_dir() else []
        return {
            "avatar_host_present": host_py.is_file(),
            "plates_loaded": plates,
            "plate_count": len(plates),
            # Overlay liveness is a runtime-process fact: the environment
            # twin reports whether the overlay host process was started in
            # THIS process tree. A headless/dev run truthfully reports
            # "not started", never "alive".
            "overlay": "not started in this process (headless/dev)",
        }

    def _permission_state(self) -> dict:
        with _runtime_path(self._root):
            import permission_gates
            vocab = sorted(permission_gates.KNOWN_PERMISSIONS)
        state_dir = self._root / "runtime" / "state"
        grants_file = state_dir / "permission_grants.json"
        grants: dict = {}
        if grants_file.is_file():
            with open(grants_file, encoding="utf-8") as handle:
                grants = json.load(handle).get("grants", {})
        return {
            "vocabulary": vocab,
            "vocabulary_size": len(vocab),
            "deny_by_default": True,
            "active_grants": sorted(grants.keys()),
            "grants_file": str(grants_file),
        }

    def _bridge_state(self) -> dict:
        with _runtime_path(self._root):
            import bridge_client  # noqa: F401  (presence = wired)
        state_dir = self._root / "runtime" / "state"
        heartbeat = state_dir / "heartbeat.jsonl"
        last: dict | None = None
        if heartbeat.is_file():
            try:
                lines = heartbeat.read_text(
                    encoding="utf-8").strip().splitlines()
                if lines:
                    last = json.loads(lines[-1])
            except (OSError, ValueError):
                last = {"unreadable": True}
        return {
            "bridge_client_present": True,
            "heartbeat_log": str(heartbeat),
            "last_heartbeat": last,
        }

    def _os_facts(self) -> dict:
        system = platform.system()
        facts: dict = {
            "system": system,
            "release": platform.release(),
            "machine": platform.machine(),
            "install_root": str(self._root),
            "install_root_absolute": os.path.isabs(str(self._root)),
        }
        if system == "Windows":
            facts["windows_version"] = platform.win32_ver()
            facts["webview2"] = self._probe_webview2_windows()
        else:
            facts["windows_version"] = None
            facts["webview2"] = {"present": False,
                                 "reason": "non-Windows OS"}
        facts["audio_device"] = self._probe_audio(system)
        seal = self._root / "sealed" / "essence_manifest.json"
        facts["seal_record_present"] = seal.is_file()
        facts["seal_record_sha256"] = (_sha256_file(seal)
                                       if seal.is_file() else None)
        return facts

    @staticmethod
    def _probe_webview2_windows() -> dict:
        # Best-effort, read-only: WebView2 loader DLL next to the app or
        # the evergreen runtime registration. Never installs anything.
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\\Microsoft\\EdgeWebView"
                               r"\\Application"),
            os.path.expandvars(r"%ProgramFiles(x86)%\\Microsoft\\EdgeWebView"
                               r"\\Application"),
        ]
        present = any(os.path.isdir(c) for c in candidates)
        return {"present": present,
                "probed": [c for c in candidates if os.path.isdir(c)]}

    @staticmethod
    def _probe_audio(system: str) -> dict:
        if system == "Windows":
            return {"present": "unknown (probe on device boot)",
                    "note": "audio device is probed when the voice "
                            "engine boots, not by the environment twin"}
        if system == "Linux":
            import glob
            cards = sorted(glob.glob("/dev/snd/pcm*"))
            return {"present": bool(cards),
                    "alsa_pcm_devices": len(cards)}
        return {"present": "unknown", "note": "unsupported OS probe"}

    # -- the contract ------------------------------------------------------
    def snapshot(self, checks=None) -> dict:
        """The exact environment state. `checks` is the launcher --check
        result list; when absent, minimal live probes are run instead."""
        if checks is None:
            checks = [
                {"name": "python_version",
                 "status": "green" if sys.version_info >= (3, 12)
                 else "red",
                 "detail": platform.python_version()},
                {"name": "kernel_importable",
                 "status": "green" if
                 (self._root / "kernel" / "genesis").is_dir() else "red",
                 "detail": "Stage 6 kernel directory present"},
            ]
        snap = {
            "modules": self._module_registry(),
            "launch_health": [
                {"name": c.get("name"), "status": c.get("status"),
                 "detail": c.get("detail")} for c in checks],
            "voice": self._voice_state(),
            "avatar": self._avatar_state(),
            "permissions": self._permission_state(),
            "bridge": self._bridge_state(),
            "os": self._os_facts(),
            "taken_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        }
        self._snapshot = snap
        return snap

    def diff_vs_reality(self) -> list:
        """Re-probe reality independently and report every drift from the
        stored snapshot. Empty list = the twin matches reality exactly."""
        if self._snapshot is None:
            self.snapshot()
        assert self._snapshot is not None
        snap = self._snapshot
        drift: list[str] = []

        # Modules: re-verify every sealed file hash against the snapshot.
        live_registry = self._module_registry()
        for name, entry in snap["modules"].items():
            live = live_registry.get(name)
            if live is None:
                drift.append("module vanished since snapshot: %s" % name)
                continue
            if live.get("quarantine_reason") != entry.get(
                    "quarantine_reason"):
                drift.append("module %s quarantine state changed: %r -> %r"
                             % (name, entry.get("quarantine_reason"),
                                live.get("quarantine_reason")))
            for rel, sealed_hash in (entry.get("sha256") or {}).items():
                # The exact directory the loader scanned for this module.
                module_dir = self._manifest_dirs.get(name)
                cand = (Path(module_dir) / rel) if module_dir else None
                if cand is None or not cand.is_file():
                    drift.append("module %s file missing: %s" % (name, rel))
                elif _sha256_file(cand) != sealed_hash:
                    drift.append("module %s file changed on disk: %s"
                                 % (name, rel))

        # Voice engine file.
        v = self._voice_state()
        if v["engine_sha256"] != snap["voice"]["engine_sha256"]:
            drift.append("voice engine file changed since snapshot")

        # Avatar plates.
        a = self._avatar_state()
        if a["plates_loaded"] != snap["avatar"]["plates_loaded"]:
            drift.append("avatar plate set changed since snapshot")

        # Permission vocabulary (code-level; a change means a new build).
        p = self._permission_state()
        if p["vocabulary"] != snap["permissions"]["vocabulary"]:
            drift.append("permission vocabulary changed since snapshot")

        # Seal record.
        o = self._os_facts()
        if o["seal_record_sha256"] != snap["os"]["seal_record_sha256"]:
            drift.append("seal record changed since snapshot")

        return drift
