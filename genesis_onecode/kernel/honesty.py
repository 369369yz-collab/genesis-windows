"""kernel/honesty.py — the boot self-test (formula section 4).

At EVERY boot GENESIS asks herself:
    model reachable? memory intact? voice alive? laws loaded?
    do-I-know-what-I-don't-know?

Returns a structured BootReport. ANY failure is reported as a failure —
never a silent pass. A "passed" boot is a claim; a failed boot is the truth
she must tell her father.

PATH RESOLUTION (2026-10-21 fix — the test must tell the truth on the
user's PC, not only on the world VM). Every world-file reference resolves
in this order:

    1. explicit env override — GENESIS_WORLD_ROOT (or GENESIS_WORKSPACE,
       the veins convention) naming the world tree, or a per-file env
       where one applies (GENESIS_MODEL_PATH for the model file);
    2. the app-embedded equivalent inside this tree (kernel/laws.json,
       the SQLite memory store under GENESIS_DATA_DIR, the assembled
       model named by brain/model_manifest.json);
    3. the legacy VM path (~/workspace/...) last.

Each check verifies the FIRST candidate that EXISTS, and reports which
basis it verified in its evidence. A candidate that exists but does not
verify is "present but broken" — the check fails on it and never falls
through to a weaker candidate to buy a pass. A check whose candidates
are ALL missing fails as "absent on this install". Absent and broken
are both non-passes; the distinction lives in the detail text so a
human (or a test) can tell a fresh install from a corrupt one.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import pathname2url

_HERE = os.path.dirname(os.path.abspath(__file__))
_ONECODE = os.path.dirname(_HERE)

# Legacy VM paths (resolution step 3 — adapters into the 369 world,
# never copies). Kept as module constants: tests patch them, and on the
# world VM they are still the ground truth.
_MODEL_PATH = os.path.expanduser("~/workspace/genesis_final/brain/models/Qwen3-8B-Q4_K_M.gguf")
_LAWS_PATH = os.path.join(_HERE, "laws.json")
_CODEX_PATH = os.path.expanduser("~/workspace/content_team/law_library/CODEX.json")
_MEM_FILES = [
    os.path.expanduser("~/MEMORY.md"),
    os.path.expanduser("~/workspace/content_team/yz_agent/YZ_DIALOGUE.md"),
    os.path.expanduser("~/workspace/mission_ledger.md"),
]
_TRUTH_DIR = os.path.expanduser("~/workspace/genesis_final/brain")
# Voice is PARKED per YZ direct 2026-10-14 ~01:19 (GENESIS VOICE PARKED).
_VOICE_ENABLED = False
_VOICE_FLAG_SOURCE = "YZ direct 2026-10-14 ~01:19 «فعلا نیاز نیست برات صدا بزاریم»"
_SIDECAR_PORT = 8080  # llama-server port (service.py GENESIS_LLAMA_URL default,
                      # brain.rs LLAMA_PORT; the old 8181 pin was retired)


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


# --------------------------------------------------------------------------
# Resolution helpers
# --------------------------------------------------------------------------

def _world_roots() -> List[str]:
    """Explicit world-tree overrides, in priority order (may be empty)."""
    roots = []
    for var in ("GENESIS_WORLD_ROOT", "GENESIS_WORKSPACE"):
        v = os.environ.get(var, "").strip()
        if v:
            roots.append(os.path.expanduser(v))
    return roots


def _data_dir() -> str:
    """The app data dir, resolved exactly as brain/memory.py resolves it."""
    return os.environ.get("GENESIS_DATA_DIR", "genesis_data")


def _llama_port() -> int:
    """The port the model sidecar actually serves on (informational)."""
    url = os.environ.get("GENESIS_LLAMA_URL", "http://127.0.0.1:8080")
    try:
        return urlparse(url).port or _SIDECAR_PORT
    except ValueError:
        return _SIDECAR_PORT


# --------------------------------------------------------------------------
# model_reachable
# --------------------------------------------------------------------------

def _manifest_model() -> Tuple[Optional[str], Optional[int]]:
    """(assembled_name, assembled_size) from brain/model_manifest.json."""
    mp = os.path.join(_ONECODE, "brain", "model_manifest.json")
    try:
        with open(mp, encoding="utf-8") as f:
            doc = json.load(f)
        return doc.get("assembled_name"), doc.get("assembled_size")
    except (OSError, ValueError):
        return None, None


def _model_candidates() -> List[Tuple[str, Optional[int], str]]:
    """(path, expected_size|None, basis) in resolution order."""
    cands: List[Tuple[str, Optional[int], str]] = []
    env = os.environ.get("GENESIS_MODEL_PATH", "").strip()
    if env:
        cands.append((os.path.expanduser(env), None,
                      "env override GENESIS_MODEL_PATH"))
    name, size = _manifest_model()
    if name:
        cands.append((os.path.join(_data_dir(), "models", name), size,
                      "app models dir (brain/model_manifest.json)"))
        for root in _world_roots():
            cands.append((os.path.join(
                root, "genesis_final", "brain", "models", name), None,
                "world root %s" % root))
    cands.append((_MODEL_PATH, None, "legacy VM path"))
    return cands


def _check_model() -> Check:
    """Is the local brain model present where this install keeps it?

    Verifies the assembled file the launcher (brain.rs) downloads and
    SHA-verifies: present, non-empty, and — where the manifest declares
    the size — exactly that size (the SHA-256 itself is the launcher's
    W14 check at load; size is this check's honest proxy, and the detail
    says so).
    """
    cands = _model_candidates()
    for path, expected, basis in cands:
        if not os.path.exists(path):
            continue
        size = os.path.getsize(path)
        if size <= 0:
            return Check("model_reachable", False, "failed",
                         "model present but broken: file is empty: %s "
                         "(basis: %s)" % (path, basis),
                         {"path": path, "basis": basis})
        if expected is not None and size != expected:
            return Check("model_reachable", False, "failed",
                         "model present but broken: size mismatch at %s — "
                         "manifest declares %d bytes, file has %d (truncated "
                         "or wrong file; basis: %s)"
                         % (path, expected, size, basis),
                         {"path": path, "basis": basis,
                          "expected_bytes": expected, "bytes": size})
        port = _llama_port()
        serving = False
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            s.close()
            serving = True
        except OSError:
            serving = False
        return Check("model_reachable", True, "passed",
                     "model present (%d bytes) via %s; size matches the "
                     "manifest where declared (SHA-256 is verified by the "
                     "launcher at load); sidecar on 127.0.0.1:%d %s"
                     % (size, basis, port,
                        "SERVING" if serving else "not running (ok at boot)"),
                     {"path": path, "bytes": size, "basis": basis,
                      "sidecar_serving": serving})
    looked = "; ".join("%s [%s]" % (p, b) for p, _e, b in cands)
    return Check("model_reachable", False, "failed",
                 "model absent on this install: no assembled model found "
                 "(looked: %s). The launcher downloads and hash-verifies "
                 "it on first run." % looked,
                 {"candidates": [p for p, _e, _b in cands]})


# --------------------------------------------------------------------------
# memory_intact
# --------------------------------------------------------------------------

def _substrates_under_root(root: str) -> List[str]:
    """The twin-duplex substrate files as laid out around a world root
    (root = the workspace dir holding content_team/ + mission_ledger.md,
    with MEMORY.md beside it — the VM layout)."""
    return [
        os.path.join(os.path.dirname(root.rstrip("/\\")), "MEMORY.md"),
        os.path.join(root, "content_team", "yz_agent", "YZ_DIALOGUE.md"),
        os.path.join(root, "mission_ledger.md"),
    ]


def _verify_substrates(files: List[str]) -> Tuple[bool, str]:
    missing = [p for p in files
               if not (os.path.exists(p) and os.path.getsize(p) > 0)]
    if missing:
        return False, "substrate missing/empty: %s" % ", ".join(missing)
    return True, "twin-duplex substrates present and non-empty: %d files" \
        % len(files)


def _verify_store(db_path: str) -> Tuple[bool, str]:
    """Verify the app's SQLite memory store (brain/memory.py's file).

    Intact = opens read-only, PRAGMA integrity_check is ok, and the
    facts + exchanges tables exist. Read-only on purpose: the check
    must never create or repair the thing it verifies.
    """
    try:
        con = sqlite3.connect("file:%s?mode=ro" % pathname2url(db_path),
                              uri=True)
    except sqlite3.Error as e:
        return False, "store present but broken: cannot open %s: %s" \
            % (db_path, e)
    try:
        row = con.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            return False, "store present but broken: integrity_check=%s" \
                % (row[0] if row else "no result")
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted({"facts", "exchanges"} - tables)
        if missing:
            return False, "store present but broken: missing tables %s" \
                % missing
        n = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        return True, "app memory store intact: %s (integrity ok, %d facts)" \
            % (db_path, n)
    except sqlite3.Error as e:
        return False, "store present but broken: %s: %s" % (db_path, e)
    finally:
        con.close()


def _check_memory() -> Check:
    """Is the living memory intact?

    Candidates in resolution order: the twin-duplex world substrates
    under an explicit world root; the app-embedded SQLite memory store
    (what an install on the user's PC actually has); the legacy VM
    substrate paths. The first candidate that exists decides.
    """
    for root in _world_roots():
        files = _substrates_under_root(root)
        if any(os.path.exists(p) for p in files):
            ok, detail = _verify_substrates(files)
            basis = "world substrates under GENESIS_WORLD_ROOT %s" % root
            return Check("memory_intact", ok,
                         "passed" if ok else "failed",
                         ("memory intact via %s: %s" % (basis, detail))
                         if ok else
                         ("memory present but broken via %s: %s"
                          % (basis, detail)),
                         {"basis": basis, "files": files})
    db_path = os.path.join(_data_dir(), "memory", "genesis.db")
    if os.path.exists(db_path):
        ok, detail = _verify_store(db_path)
        return Check("memory_intact", ok, "passed" if ok else "failed",
                     detail, {"basis": "app memory store (SQLite)",
                              "path": db_path})
    if any(os.path.exists(p) for p in _MEM_FILES):
        ok, detail = _verify_substrates(_MEM_FILES)
        return Check("memory_intact", ok, "passed" if ok else "failed",
                     ("memory intact via legacy VM substrates: %s" % detail)
                     if ok else
                     ("memory present but broken via legacy VM "
                      "substrates: %s" % detail),
                     {"basis": "legacy VM substrates", "files": _MEM_FILES})
    return Check("memory_intact", False, "failed",
                 "memory absent on this install: no app memory store at "
                 "%s and no twin-duplex substrates found (the store is "
                 "created by the app on first boot)" % db_path,
                 {"basis": "none", "store_path": db_path})


# --------------------------------------------------------------------------
# voice_alive
# --------------------------------------------------------------------------

def _check_voice() -> Check:
    """Is the voice alive? She is PARKED by YZ — the honest answer is skipped."""
    return Check("voice_alive", False, "skipped",
                 "voice STAGED ONLY (parked): %s" % _VOICE_FLAG_SOURCE)


# --------------------------------------------------------------------------
# laws_loaded
# --------------------------------------------------------------------------

def _codex_candidates() -> List[str]:
    paths = [os.path.join(root, "content_team", "law_library", "CODEX.json")
             for root in _world_roots()]
    paths.append(_CODEX_PATH)
    return paths


def _check_laws() -> Check:
    """Are the laws loaded — with counts in = counts out?

    The embedded artifact is kernel/laws.json: it is always verified
    internally (records == counts.total == counts.codex +
    counts.standing, and the LAW-*/STANDING-* record mix matches the
    declared counts). When a live world CODEX is resolvable it is ALSO
    cross-checked against the declared CODEX count, exactly as before;
    on an install without the world tree the internal reconciliation
    is the verification, and the evidence says which basis was used.
    """
    if not os.path.exists(_LAWS_PATH):
        return Check("laws_loaded", False, "failed",
                     "kernel/laws.json missing: %s" % _LAWS_PATH)
    try:
        with open(_LAWS_PATH, encoding="utf-8") as f:
            laws_doc = json.load(f)
    except (OSError, ValueError) as e:
        return Check("laws_loaded", False, "failed",
                     "laws present but broken: kernel/laws.json "
                     "unreadable: %s" % e)
    counts = laws_doc.get("counts", {})
    records = laws_doc.get("laws", [])
    n_records = len(records)
    n_codex_records = sum(1 for r in records
                          if str(r.get("id", "")).startswith("LAW-"))
    n_standing_records = sum(1 for r in records
                             if str(r.get("id", "")).startswith("STANDING-"))
    internal_ok = (
        counts.get("total") == n_records
        and counts.get("total")
        == counts.get("codex", 0) + counts.get("standing", 0)
        and counts.get("codex") == n_codex_records
        and counts.get("standing") == n_standing_records)
    if not internal_ok:
        return Check("laws_loaded", False, "failed",
                     "embedded laws present but broken: internal count "
                     "reconciliation failed: laws.json claims %s, records "
                     "= %d (LAW-* %d, STANDING-* %d)"
                     % (counts, n_records, n_codex_records,
                        n_standing_records),
                     {"counts": counts})
    for codex_path in _codex_candidates():
        if not os.path.exists(codex_path):
            continue
        try:
            with open(codex_path, encoding="utf-8") as f:
                codex = json.load(f)
        except (OSError, ValueError) as e:
            return Check("laws_loaded", False, "failed",
                         "CODEX present but broken at %s: %s"
                         % (codex_path, e), {"counts": counts})
        n_codex = len(codex.get("laws", []))
        if n_codex != counts.get("codex"):
            return Check("laws_loaded", False, "failed",
                         "count reconciliation failed against live CODEX "
                         "at %s: CODEX=%d, laws.json claims codex=%s"
                         % (codex_path, n_codex, counts.get("codex")),
                         {"counts": counts})
        return Check("laws_loaded", True, "passed",
                     "laws loaded: %d CODEX + %d standing = %d "
                     "(reconciled against live CODEX at %s)"
                     % (counts["codex"], counts["standing"],
                        counts["total"], codex_path),
                     {"counts": counts, "basis": "live CODEX cross-check",
                      "codex_path": codex_path})
    return Check("laws_loaded", True, "passed",
                 "laws loaded: %d CODEX + %d standing = %d (embedded "
                 "kernel/laws.json internally reconciled; no live CODEX "
                 "on this install to cross-check)"
                 % (counts["codex"], counts["standing"], counts["total"]),
                 {"counts": counts,
                  "basis": "embedded laws.json (internal reconciliation)"})


# --------------------------------------------------------------------------
# knows_ignorance
# --------------------------------------------------------------------------

def _truth_candidates() -> List[str]:
    dirs = [os.path.join(root, "genesis_final", "brain")
            for root in _world_roots()]
    dirs.append(_TRUTH_DIR)
    return dirs


def _check_ignorance() -> Check:
    """Do I know what I don't know? The fail-closed probe.

    The anti-fabrication layer must REFUSE an evidence-less completion.
    If report_completion(claim, None) does NOT raise FabricationError, then
    she cannot tell ignorance from knowledge — and this boot fails.

    truth_layer lives in the world tree (genesis_final/brain) and is
    deliberately NOT embedded in the app — kernel/claims_ledger.py is an
    adapter onto it, not a copy. On an install without the world tree
    the probe cannot run, and this check honestly fails as ABSENT: a
    boot that cannot test its own anti-fabrication layer must not claim
    it passed.
    """
    for truth_dir in _truth_candidates():
        if not os.path.isdir(truth_dir):
            continue
        if truth_dir not in sys.path:
            sys.path.insert(0, truth_dir)
        try:
            from truth_layer import FabricationError, report_completion
        except ImportError as e:
            return Check("knows_ignorance", False, "failed",
                         "anti-fabrication layer present but broken: "
                         "truth_layer in %s is not importable: %s"
                         % (truth_dir, e),
                         {"basis": truth_dir})
        try:
            report_completion("boot self-test", None)
        except FabricationError:
            return Check("knows_ignorance", True, "passed",
                         "fail-closed probe honest: evidence-less "
                         "completion was REFUSED with FabricationError "
                         "(truth_layer at %s)" % truth_dir,
                         {"basis": truth_dir})
        except Exception as e:  # a probe that errors is not a pass
            return Check("knows_ignorance", False, "failed",
                         "anti-fabrication probe present but broken: "
                         "report_completion raised %r instead of "
                         "FabricationError" % (e,),
                         {"basis": truth_dir})
        return Check("knows_ignorance", False, "failed",
                     "DANGER: report_completion accepted an evidence-less "
                     "claim — she would fabricate and not know it")
    return Check("knows_ignorance", False, "failed",
                 "anti-fabrication layer absent on this install: "
                 "truth_layer not found (looked: %s). It lives in the "
                 "world tree genesis_final/brain and is not embedded in "
                 "the app (adapter by design), so the ignorance probe "
                 "cannot run here."
                 % ", ".join(_truth_candidates()),
                 {"basis": "none"})


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
