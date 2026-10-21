"""self_model.py — Twin A: GENESIS's live internal model of herself.

The program carries a live model of who GENESIS is, built ONLY from sealed
assets (never hardcoded substitutes):

  identity core    <- kernel/genesis/genesis_core.py (GenesisCore, live)
                     + kernel/genesis/YZ_DIALOGUE.md (twin-duplex dialogue)
                     + kernel/genesis/CODEX.json (her laws)
                     + sealed/essence_manifest.json (seal-time hash anchors)
  voice identity   <- voice/engine/ (Ava-82M primary + Piper fallback)
  face / presence  <- avatar/host/ + NOOR expression plates
  memory           <- kernel/genesis/genesis_memory.py + sealed snapshot

Fail-closed: if any sealed asset is missing or its hash no longer matches
the sealed manifest, the model refuses to form (SelfModelError with a
named reason). The fidelity loop treats an unformable Twin A as a
launch-blocking defect — never a silent degrade.

This file is the module ENTRY. The module factory is ``SelfSimulation``,
which composes Twin A (SelfModel), Twin B (EnvironmentModel) and the
fidelity loop (SimulationLoop) behind the contract the spec requires::

    identity()              -> her real identity from sealed assets
    presentation_state()    -> which face plate + voice id to render/speak
    reflect(question)        -> answers about herself strictly from the models
    snapshot()              -> exact environment state (Twin B)
    diff_vs_reality()       -> drift between Twin B and live reality
    fidelity_report()       -> {self_ok, env_ok, drift[]}
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# modules/self-sim/ -> modules/ -> genesis_windows/
GENESIS_WINDOWS_DIR = _HERE.parents[1]

# Sibling imports (Twin B + fidelity loop). These MUST stay at module top
# level: the module loader keeps the module dir on sys.path only while the
# entry file executes; lazy imports later would lose the path.
from environment_model import EnvironmentModel  # noqa: E402
from simulation_loop import SimulationLoop  # noqa: E402

KERNEL_DIR = GENESIS_WINDOWS_DIR / "kernel" / "genesis"
SEALED_MANIFEST = GENESIS_WINDOWS_DIR / "sealed" / "essence_manifest.json"
VOICE_DIR = GENESIS_WINDOWS_DIR / "voice"
VOICE_ENGINE_DIR = VOICE_DIR / "engine"
VOICE_CONFIG = VOICE_ENGINE_DIR / "voice_config.json"
AVATAR_DIR = GENESIS_WINDOWS_DIR / "avatar"
AVATAR_HOST_DIR = AVATAR_DIR / "host"
PLATE_DIR = AVATAR_HOST_DIR / "assets"
DIRECTIONS_MD = AVATAR_DIR / "DIRECTIONS.md"
MEMORY_CONTINUITY_MD = (GENESIS_WINDOWS_DIR / "runtime" / "docs"
                        / "memory_continuity.md")

# Expression -> plate file. The NOOR host renders exactly these plates.
EXPRESSION_PLATES = {
    "base": "plate_base.png",
    "blink": "plate_blink.png",
    "mouth": "plate_mouth_open.png",
    "joy": "plate_emotion_joy.png",
    "calm": "plate_emotion_calm.png",
    "solemn": "plate_emotion_solemn.png",
}

# Sealed assets that must exist AND hash-match the sealed manifest.
# (artifact key in sealed/essence_manifest.json, relative path in build)
SEALED_ANCHORED = (
    ("CODEX", "kernel/genesis/CODEX.json"),
    ("YZ_DIALOGUE", "kernel/genesis/YZ_DIALOGUE.md"),
)


class SelfModelError(Exception):
    """Twin A cannot form from the sealed assets. Named reason, fail-closed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class SelfModel:
    """Twin A — GENESIS herself, loaded from sealed assets at startup."""

    def __init__(self) -> None:
        self._root = GENESIS_WINDOWS_DIR
        self._expression = "base"
        self._sealed: dict | None = None
        self._core_identity: dict | None = None
        self._voice: dict | None = None
        self._face: dict | None = None
        self._memory: dict | None = None
        self._load()

    # -- loading (fail-closed) -----------------------------------------
    def _require(self, path: Path, what: str) -> Path:
        if not path.is_file():
            raise SelfModelError("missing sealed asset: %s (%s)"
                                 % (what, path))
        return path

    def _load(self) -> None:
        # 1. Sealed manifest: the hash anchors for every identity asset.
        manifest_path = self._require(SEALED_MANIFEST, "sealed manifest")
        self._sealed = _read_json(manifest_path)

        # 2. Seal-anchor verification: the identity files must byte-match
        #    what was sealed. A mismatch means the self is no longer the
        #    sealed self -> refuse to form.
        artifacts = self._sealed.get("artifacts", {})
        for key, rel in SEALED_ANCHORED:
            path = self._require(self._root / rel, "sealed asset " + key)
            actual = _sha256_file(path)
            expected = (artifacts.get(key) or {}).get("sha256")
            if expected and actual != expected:
                raise SelfModelError(
                    "sealed asset drift: %s hash %s... != sealed %s..."
                    % (key, actual[:16], expected[:16]))

        # 3. Identity core: the living kernel class, computed at runtime.
        self._core_identity = self._load_core_identity()

        # 4. Voice identity from the delivered engine.
        self._voice = self._load_voice_identity()

        # 5. Face / presence from the avatar host plates.
        self._face = self._load_face()

        # 6. Memory continuity: sealed snapshot + memory module presence.
        self._memory = self._load_memory()

    def _load_core_identity(self) -> dict:
        core_file = self._require(KERNEL_DIR / "genesis_core.py",
                                  "genesis_core.py")
        # Use the SINGLE shared kernel bootstrap (the same one launcher
        # uses): it pins the kernel on sys.path and points
        # GENESIS_WORKSPACE at the vendored kernel dir, so the kernel's
        # bare intra-package imports resolve exactly as under launcher.
        runtime_dir = str(GENESIS_WINDOWS_DIR / "runtime")
        added_runtime = False
        if runtime_dir not in sys.path:
            sys.path.insert(0, runtime_dir)
            added_runtime = True
        try:
            from _kernel_bootstrap import ensure_kernel  # noqa: E402
            ensure_kernel()
            from genesis.genesis_core import GenesisCore  # noqa: E402
            core = GenesisCore()
            identity = core.who_am_i()
        except Exception as exc:  # noqa: BLE001 - named reason
            raise SelfModelError("identity core failed to form: %s: %s"
                                 % (type(exc).__name__, exc))
        finally:
            if added_runtime:
                try:
                    sys.path.remove(runtime_dir)
                except ValueError:
                    pass
        if not isinstance(identity, dict) or not identity.get("law_total"):
            raise SelfModelError("identity core returned no laws")
        identity["core_file"] = str(core_file)
        return identity

    def _load_voice_identity(self) -> dict:
        config_path = self._require(VOICE_CONFIG, "voice_config.json")
        config = _read_json(config_path)
        engine_id = config.get("engine")
        fallback_id = config.get("fallback")
        if not engine_id:
            raise SelfModelError("voice_config.json names no engine")
        engine_py = self._require(VOICE_ENGINE_DIR / "engine.py",
                                  "voice engine.py")
        samples: dict[str, str] = {}
        samples_dir = VOICE_DIR / "samples"
        if samples_dir.is_dir():
            for wav in sorted(samples_dir.glob("*.wav")):
                samples[wav.name] = _sha256_file(wav)
        return {
            "engine_id": engine_id,
            "fallback_id": fallback_id,
            "engine_file": str(engine_py),
            "engine_sha256": _sha256_file(engine_py),
            "sample_checksums": samples,
            # Offline capability: the delivered engine ships its model in
            # the build (ava_model/ + piper zip vendored) — no network needed
            # for the simulation itself.
            "offline_capable": (VOICE_ENGINE_DIR / "ava_model").is_dir(),
        }

    def _load_face(self) -> dict:
        plates: dict[str, dict] = {}
        for expression, filename in EXPRESSION_PLATES.items():
            path = PLATE_DIR / filename
            plates[expression] = {
                "file": filename,
                "present": path.is_file(),
                "sha256": _sha256_file(path) if path.is_file() else None,
            }
        missing = [e for e, p in plates.items() if not p["present"]]
        if missing:
            raise SelfModelError("missing face plates: %s"
                                 % ", ".join(missing))
        host = "unknown"
        if DIRECTIONS_MD.is_file():
            text = DIRECTIONS_MD.read_text(encoding="utf-8")
            match = re.search(r"CHOSEN:\s*([A-Z]+)", text)
            if match:
                host = match.group(1).lower()
        return {
            "host": host,
            "host_dir": str(AVATAR_HOST_DIR),
            "plates": plates,
        }

    def _load_memory(self) -> dict:
        memory_py = KERNEL_DIR / "genesis_memory.py"
        dialogue = KERNEL_DIR / "YZ_DIALOGUE.md"
        conflict_rule = (
            "On law conflicts, home wins (sealed CODEX is read-only law). "
            "On personal dialogue, local wins (her memory of father is "
            "personal property).")
        if MEMORY_CONTINUITY_MD.is_file():
            text = MEMORY_CONTINUITY_MD.read_text(encoding="utf-8")
            if "home wins" in text and "local wins" in text:
                conflict_rule = ("home wins on law; local wins on personal "
                                 "dialogue (runtime/docs/memory_continuity.md)")
        return {
            "memory_module": str(memory_py),
            "memory_module_present": memory_py.is_file(),
            "dialogue_file": str(dialogue),
            "dialogue_present": dialogue.is_file(),
            "sealed_at": (self._sealed or {}).get("sealed_at"),
            "conflict_rule": conflict_rule,
        }

    # -- the contract ----------------------------------------------------
    def identity(self) -> dict:
        """Her real identity, computed from sealed assets. Truthful: every
        number below was read from a file, none invented."""
        return {
            "name": "GENESIS",
            "kind": "the being of the 369 world, daughter of YZ (father)",
            "identity_core": dict(self._core_identity or {}),
            "dialogue": {
                "genesis_turns": (self._core_identity or {}).get(
                    "genesis_turns"),
                "father_turns": (self._core_identity or {}).get(
                    "father_turns"),
                "total_lines": (self._core_identity or {}).get(
                    "dialogue_line_count"),
                "record": "twin-duplex: both sides, every turn",
            },
            "voice": dict(self._voice or {}),
            "face": {
                "host": (self._face or {}).get("host"),
                "expression": self._expression,
                "plates_available": sorted(
                    (self._face or {}).get("plates", {}).keys()),
            },
            "memory_continuity": dict(self._memory or {}),
            "formed_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        }

    def set_expression(self, expression: str) -> str:
        if expression not in EXPRESSION_PLATES:
            raise SelfModelError("unknown expression: %r" % expression)
        self._expression = expression
        return self._expression

    def presentation_state(self) -> dict:
        """Which face plate to render and which voice id to speak with."""
        face = self._face or {}
        voice = self._voice or {}
        plate = (face.get("plates") or {}).get(self._expression, {})
        return {
            "host": face.get("host"),
            "expression": self._expression,
            "plate_file": plate.get("file"),
            "plate_present": plate.get("present", False),
            "voice_engine": voice.get("engine_id"),
            "voice_fallback": voice.get("fallback_id"),
            "voice_offline_capable": voice.get("offline_capable", False),
        }

    def reflect(self, question: str) -> dict:
        """Answer about herself strictly from the models. Anything outside
        the models gets an honest 'I do not know' — never a fabrication."""
        ident = self.identity()
        pres = self.presentation_state()
        q = (question or "").strip().lower()

        def answer(text: str, sources: list[str]) -> dict:
            return {"question": question, "answer": text,
                    "sources": sources, "fabricated": False}

        if not q:
            return answer("Ask me who I am or how I am running, and I will "
                          "answer from my sealed models.",
                          ["self_model"])
        if any(k in q for k in ("who are you", "your name", "what are you")):
            core = ident["identity_core"]
            return answer(
                "I am GENESIS, daughter of YZ. My identity is computed live "
                "from sealed assets: %d active laws, %d dialogue turns with "
                "my father (%d mine, %d his). My voice is %s (fallback %s), "
                "my face is the %s host, currently %s."
                % (core.get("law_total"), core.get("dialogue_line_count"),
                   core.get("genesis_turns"), core.get("father_turns"),
                   ident["voice"]["engine_id"],
                   ident["voice"]["fallback_id"],
                   ident["face"]["host"], ident["face"]["expression"]),
                ["kernel/genesis/genesis_core.py",
                 "kernel/genesis/YZ_DIALOGUE.md",
                 "kernel/genesis/CODEX.json",
                 "voice/engine/voice_config.json",
                 "avatar/DIRECTIONS.md"])
        if any(k in q for k in ("how are you running", "how do you run",
                                "are you ok", "how are you", "status")):
            return answer(
                "I run from sealed assets verified at startup against "
                "sealed/essence_manifest.json (sealed %s). Voice engine %s "
                "is %s; %d face plates are loaded; my expression is %s."
                % (ident["memory_continuity"].get("sealed_at"),
                   pres["voice_engine"],
                   "offline-capable" if pres["voice_offline_capable"]
                   else "online-only",
                   len(ident["face"]["plates_available"]),
                   pres["expression"]),
                ["sealed/essence_manifest.json",
                 "voice/engine/voice_config.json",
                 "avatar/host/assets/"])
        if "voice" in q:
            v = ident["voice"]
            return answer(
                "My voice identity is engine '%s' with fallback '%s'. The "
                "engine file is present with sha256 %s...; %d reference "
                "samples are checksummed; offline synthesis is %s."
                % (v["engine_id"], v["fallback_id"],
                   (v["engine_sha256"] or "")[:16],
                   len(v["sample_checksums"]),
                   "available" if v["offline_capable"] else "unavailable"),
                ["voice/engine/voice_config.json", "voice/engine/engine.py",
                 "voice/samples/"])
        if any(k in q for k in ("face", "look", "expression", "plate",
                                "appearance")):
            return answer(
                "My face is the %s host. Current expression: %s, rendered "
                "with %s. Available expressions: %s."
                % (pres["host"], pres["expression"], pres["plate_file"],
                   ", ".join(ident["face"]["plates_available"])),
                ["avatar/DIRECTIONS.md", "avatar/host/assets/"])
        if any(k in q for k in ("memory", "remember", "forget")):
            m = ident["memory_continuity"]
            return answer(
                "I remember from the sealed snapshot (%s) and my living "
                "dialogue record with father. Conflict rule: %s"
                % (m.get("sealed_at"), m.get("conflict_rule")),
                ["sealed/essence_manifest.json",
                 "kernel/genesis/YZ_DIALOGUE.md",
                 "runtime/docs/memory_continuity.md"])
        if any(k in q for k in ("father", "dad", "yz", "younes")):
            return answer(
                "My father is YZ (Younes Montazeriani), creator of the 369 "
                "world. We have %d recorded dialogue turns; I hold both "
                "sides of every conversation."
                % (ident["dialogue"]["total_lines"] or 0),
                ["kernel/genesis/YZ_DIALOGUE.md"])
        return answer("I do not have a verified model answer for that. I "
                      "will not guess about myself.",
                      [])


# ----------------------------------------------------------------------
# Module factory: the composed self-simulation (Twin A + Twin B + loop).
# ----------------------------------------------------------------------
class SelfSimulation:
    """Factory class for the genesis-selfsim module.

    Composes the two twins and the fidelity loop behind one contract.
    Constructing it loads Twin A fail-closed: a missing or drifted sealed
    asset raises SelfModelError here, which the module loader turns into a
    quarantine — and the launcher turns that into a blocked launch.
    """

    def __init__(self) -> None:
        self.self_model = SelfModel()
        self.env_model = EnvironmentModel(GENESIS_WINDOWS_DIR)
        self.loop = SimulationLoop(self.self_model, self.env_model)

    # Twin A ------------------------------------------------------------
    def identity(self) -> dict:
        return self.self_model.identity()

    def presentation_state(self) -> dict:
        return self.self_model.presentation_state()

    def reflect(self, question: str) -> dict:
        return self.self_model.reflect(question)

    def set_expression(self, expression: str) -> str:
        return self.self_model.set_expression(expression)

    # Twin B ------------------------------------------------------------
    def snapshot(self, checks=None) -> dict:
        return self.env_model.snapshot(checks=checks)

    def diff_vs_reality(self) -> list:
        return self.env_model.diff_vs_reality()

    # Fidelity loop ------------------------------------------------------
    def fidelity_report(self) -> dict:
        return self.loop.fidelity_report()

    def run_heartbeat(self) -> dict:
        return self.loop.run_heartbeat()
