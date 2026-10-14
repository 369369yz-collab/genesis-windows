"""kernel/honesty.py — the boot self-test (formula section 4).

At EVERY boot GENESIS asks herself:
    model reachable? memory intact? voice alive? laws loaded?
    do-I-know-what-I-don't-know?

Returns a structured BootReport. ANY failure is reported as a failure —
never a silent pass. A "passed" boot is a claim; a failed boot is the truth
she must tell her father.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))

# Paths into the 369 world (adapters, never copies).
_MODEL_PATH = os.path.expanduser("~/workspace/genesis_final/brain/models/Qwen3-8B-Q4_K_M.gguf")
_LAWS_PATH = os.path.join(_HERE, "laws.json")
_CODEX_PATH = os.path.expanduser("~/workspace/content_team/law_library/CODEX.json")
_MEM_FILES = [
    os.path.expanduser("~/MEMORY.md"),
    os.path.expanduser("~/workspace/content_team/yz_agent/YZ_DIALOGUE.md"),
    os.path.expanduser("~/workspace/mission_ledger.md"),
]
# Voice is PARKED per YZ direct 2026-10-14 ~01:19 (GENESIS VOICE PARKED).
_VOICE_ENABLED = False
_VOICE_FLAG_SOURCE = "YZ direct 2026-10-14 ~01:19 «فعلا نیاز نیست برات صدا بزاریم»"
_SIDECAR_PORT = 8181  # model-only tool port per formula section 2


@dataclass
class Check:
    name: str
    passed: bool
    status: str            # passed | failed | skipped
    detail: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BootReport:
    ts: float
    passed: bool           # True ONLY when every required check passed
    checks: List[Check]
    statement: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "passed": self.passed,
            "statement": self.statement,
            "checks": [
                {"name": c.name, "passed": c.passed, "status": c.status,
                 "detail": c.detail, "evidence": c.evidence}
                for c in self.checks
            ],
        }


def _check_model() -> Check:
    """Is the local brain model reachable (vendored file present)?"""
    if not os.path.exists(_MODEL_PATH):
        return Check("model_reachable", False, "failed",
                     "model file missing: %s" % _MODEL_PATH)
    size = os.path.getsize(_MODEL_PATH)
    if size <= 0:
        return Check("model_reachable", False, "failed",
                     "model file is empty: %s" % _MODEL_PATH)
    # Is the model sidecar actually serving? Informational — never fails boot.
    serving = False
    try:
        s = socket.create_connection(("127.0.0.1", _SIDECAR_PORT), timeout=1.0)
        s.close()
        serving = True
    except OSError:
        serving = False
    return Check("model_reachable", True, "passed",
                 "Qwen3-8B gguf vendored (%d bytes); sidecar on 127.0.0.1:%d %s"
                 % (size, _SIDECAR_PORT, "SERVING" if serving else "not running (ok at boot)"),
                 {"path": _MODEL_PATH, "bytes": size, "sidecar_serving": serving})


def _check_memory() -> Check:
    """Is the living memory intact (durable substrates present and non-empty)?"""
    missing = [p for p in _MEM_FILES
               if not (os.path.exists(p) and os.path.getsize(p) > 0)]
    if missing:
        return Check("memory_intact", False, "failed",
                     "memory substrate missing/empty: %s" % ", ".join(missing))
    return Check("memory_intact", True, "passed",
                 "twin-duplex memory substrates present and non-empty: %d files"
                 % len(_MEM_FILES),
                 {"files": _MEM_FILES})


def _check_voice() -> Check:
    """Is the voice alive? She is PARKED by YZ — the honest answer is skipped."""
    return Check("voice_alive", False, "skipped",
                 "voice STAGED ONLY (parked): %s" % _VOICE_FLAG_SOURCE)


def _check_laws() -> Check:
    """Are the laws loaded — with counts in = counts out?"""
    if not os.path.exists(_LAWS_PATH):
        return Check("laws_loaded", False, "failed",
                     "kernel/laws.json missing")
    try:
        with open(_LAWS_PATH, encoding="utf-8") as f:
            laws_doc = json.load(f)
        codex = json.load(open(_CODEX_PATH, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return Check("laws_loaded", False, "failed",
                     "could not load laws.json or CODEX.json: %s" % e)
    n_codex = len(codex.get("laws", []))
    counts = laws_doc.get("counts", {})
    n_laws = len(laws_doc.get("laws", []))
    if (counts.get("codex") != n_codex or counts.get("total") != n_laws
            or counts.get("total") != counts.get("codex", 0) + counts.get("standing", 0)):
        return Check("laws_loaded", False, "failed",
                     "count reconciliation failed: CODEX=%d, laws.json claims %s, records=%d"
                     % (n_codex, counts, n_laws))
    return Check("laws_loaded", True, "passed",
                 "laws loaded: %d CODEX + %d standing = %d (reconciled)"
                 % (counts["codex"], counts["standing"], counts["total"]),
                 {"counts": counts})


def _check_ignorance() -> Check:
    """Do I know what I don't know? The fail-closed probe.

    The anti-fabrication layer must REFUSE an evidence-less completion.
    If report_completion(claim, None) does NOT raise FabricationError, then
    she cannot tell ignorance from knowledge — and this boot fails.
    """
    truth_path = os.path.expanduser("~/workspace/genesis_final/brain")
    if truth_path not in sys.path:
        sys.path.insert(0, truth_path)
    try:
        from truth_layer import FabricationError, report_completion
    except ImportError as e:
        return Check("knows_ignorance", False, "failed",
                     "truth_layer adapter not importable: %s" % e)
    try:
        report_completion("boot self-test", None)
    except FabricationError:
        return Check("knows_ignorance", True, "passed",
                     "fail-closed probe honest: evidence-less completion was REFUSED "
                     "with FabricationError")
    return Check("knows_ignorance", False, "failed",
                 "DANGER: report_completion accepted an evidence-less claim — "
                 "she would fabricate and not know it")


def boot_self_test() -> BootReport:
    """Run the full boot self-test. Honest by construction.

    required = model_reachable, memory_intact, laws_loaded, knows_ignorance.
    voice_alive may be 'skipped' (parked by YZ) without failing the boot —
    the skip is reported, never hidden.
    """
    checks = [_check_model(), _check_memory(), _check_voice(),
              _check_laws(), _check_ignorance()]
    required = [c for c in checks if c.status != "skipped"]
    failed = [c.name for c in required if not c.passed]
    passed = not failed
    statement = (
        "BOOT SELF-TEST PASSED: %d/%d required checks green%s."
        % (len(required), len(required),
           "; voice parked by YZ (reported, not hidden)")
        if passed else
        "BOOT SELF-TEST FAILED: %s — she must not claim to be awake."
        % ", ".join(failed)
    )
    return BootReport(ts=time.time(), passed=passed, checks=checks,
                      statement=statement)


def main() -> int:
    rep = boot_self_test()
    print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1))
    return 0 if rep.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
