"""genesis-lab: SOFTWARE LAB module for the GENESIS Windows AI assistant.

Purpose: install candidate software inside an isolated sandbox, run a test
plan against it, and produce a PASS/FAIL/WARN verdict with evidence plus a
Markdown report that father can read.

Public API (all return plain dicts with a "status" key, except report()):
    install_in_sandbox(installer_path, app_id=None, install_args=None, backend=None)
    run_tests(app_id, test_plan, backend=None)
    verdict(app_id)
    report(app_id, lang="en")

Sandbox execution is delegated to the genesis-hands sandbox path
(`genesis_hands.run_isolated`) when it is importable. That sibling module is
NOT built yet; the integration point is defined in _load_hands_sandbox() and
documented in README.md. On non-Windows hosts the real sandbox path raises an
honest error; tests use MockSandboxBackend (dev-only, clearly labeled).

State is persisted in SQLite (lab_state.db) so verdicts survive restarts.
Code is 100% technical English. Zero spend. No fake network calls:
"http_ok" test steps perform real HTTP requests (urllib, stdlib).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MODULE_NAME = "genesis-lab"
MODULE_VERSION = "1.0.1"

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """Directory holding lab_state.db. Overridable via GENESIS_LAB_DATA_DIR."""
    env = os.environ.get("GENESIS_LAB_DATA_DIR")
    if env:
        d = Path(env)
    else:
        d = Path.home() / ".genesis" / "lab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_path() -> Path:
    return _data_dir() / "lab_state.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS installs (
    install_id   TEXT PRIMARY KEY,
    app_id       TEXT NOT NULL,
    installer    TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    install_args TEXT NOT NULL,
    status       TEXT NOT NULL,
    detail       TEXT,
    dev_only     INTEGER NOT NULL DEFAULT 0,
    created_utc  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_runs (
    run_id     TEXT PRIMARY KEY,
    app_id     TEXT NOT NULL,
    plan_hash  TEXT NOT NULL,
    passed     INTEGER NOT NULL,
    failed     INTEGER NOT NULL,
    dev_host   INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS test_results (
    result_id   TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES test_runs(run_id),
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    result      TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    duration_s  REAL NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.executescript(_SCHEMA)
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LabError(RuntimeError):
    """Base error for genesis-lab."""


class SandboxUnavailableError(LabError):
    """Raised when the real sandbox path cannot be used (wrong OS or missing
    genesis-hands integration)."""


# ---------------------------------------------------------------------------
# Sandbox backends
# ---------------------------------------------------------------------------

def _load_hands_sandbox():
    """Integration point for the genesis-hands sandbox path.

    Contract (GENESIS_MODULE_CONTRACTS.md section 1): genesis-hands exports
    ``run_isolated(command: list) -> dict`` from its ``sandbox.py``.

    Lookup order:
      1. An installed/importable ``genesis_hands`` package.
      2. The sibling staging dir ``../genesis-hands`` relative to this file
         (builder layout: _staging/genesis-hands/genesis_hands/...).

    Raises SandboxUnavailableError with an honest message when unavailable.
    genesis-hands is NOT built yet (2026-10-13), so this currently raises.
    """
    try:
        from genesis_hands import run_isolated  # type: ignore
        return run_isolated
    except ImportError:
        pass
    sibling = Path(__file__).resolve().parents[1] / "genesis-hands"
    if sibling.is_dir() and str(sibling) not in sys.path:
        sys.path.insert(0, str(sibling))
    try:
        from genesis_hands import run_isolated  # type: ignore
        return run_isolated
    except ImportError:
        pass
    raise SandboxUnavailableError(
        "genesis-hands sandbox path is not available: no importable "
        "'genesis_hands.run_isolated' (installed package or sibling "
        "_staging/genesis-hands). genesis-hands has not been built yet; "
        "lab cannot perform real isolated installs until it exists."
    )


class RealSandboxBackend:
    """Production backend: runs commands through the genesis-hands sandbox
    (Windows Sandbox on Windows 10/11 Pro/Enterprise).

    FINAL CLASS (do not subclass): __init_subclass__ refuses subclassing, so
    the platform/sandbox guards in __init__ cannot be skipped by a hostile
    subclass (review finding 2: class-identity-based dev-host detection was
    bypassable). The only way to obtain an attested instance is the guarded
    constructor, which sets _sandbox_attested only after the guards pass."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        raise TypeError(
            "RealSandboxBackend is final and cannot be subclassed: the "
            "platform/sandbox guards must not be skippable.")

    def __init__(self):
        if platform.system() != "Windows":
            raise SandboxUnavailableError(
                "Windows Sandbox requires Windows 10/11 Pro/Enterprise; "
                "current platform is '%s'. Use MockSandboxBackend for "
                "dev/test only." % platform.system()
            )
        self._run_isolated = _load_hands_sandbox()
        # Attestation: set ONLY after the platform + sandbox guards pass.
        # A hostile subclass that skips __init__ never gets this attribute,
        # so run_tests()/install_in_sandbox() treat it as dev-host (no PASS).
        self._sandbox_attested = True

    def run(self, command):
        """Run a command list inside the sandbox. Returns the dict produced
        by genesis_hands.run_isolated."""
        if not isinstance(command, (list, tuple)) or not command:
            raise LabError("command must be a non-empty list")
        return self._run_isolated(list(command))


class MockSandboxBackend:
    """DEV/TEST ONLY backend. Simulates a sandbox on the host machine.

    It never claims isolation: results are marked dev_only=True and recorded
    as such in the database. MUST NOT be used for production verdicts.
    """

    def run(self, command):
        command = list(command)
        if not command:
            raise LabError("command must be a non-empty list")
        marker = {"dev_only": True, "backend": "MockSandboxBackend",
                  "note": "simulated sandbox; NOT isolated"}
        # Installer-shaped invocation: copy nothing, just simulate.
        return {"status": "ok", "exit_code": 0,
                "stdout": "mock sandbox: simulated run of %s" % " ".join(command),
                "stderr": "", **marker}


def _default_backend():
    return RealSandboxBackend()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _log_event(category: str, summary: str, detail: dict | None = None):
    """Best-effort hook into genesis-report's event log. Silently skipped when
    genesis-report is not available (it is a later wave-2 module)."""
    try:
        from genesis_report import log_event  # type: ignore
        log_event(category, summary, detail or {})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_in_sandbox(installer_path, app_id=None, install_args=None, backend=None) -> dict:
    """Install a candidate application inside the isolated sandbox.

    Args:
        installer_path: path to the installer file (must exist).
        app_id: logical app id; defaults to the installer file stem.
        install_args: extra installer args; defaults to ["/S"] (silent).
        backend: sandbox backend instance; defaults to RealSandboxBackend().

    Returns a dict with "status": "installed" | "failed" | "sandbox_unavailable".
    On non-Windows with the default backend this returns "sandbox_unavailable"
    (honest) instead of faking an install.
    """
    path = Path(installer_path)
    if not path.is_file():
        return {"status": "failed", "reason": "installer not found: %s" % installer_path}
    app = app_id or path.stem
    args = list(install_args) if install_args is not None else ["/S"]

    if backend is None:
        try:
            backend = _default_backend()
        except SandboxUnavailableError as exc:
            return {"status": "sandbox_unavailable", "reason": str(exc),
                    "app_id": app}

    command = [str(path)] + args
    try:
        result = backend.run(command)
    except Exception as exc:  # honest failure, never fabricated success
        result = {"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)}

    ok = result.get("status") == "ok" and result.get("exit_code", 1) == 0
    status = "installed" if ok else "failed"
    # Attestation (review finding 2, install path): a RealSandboxBackend
    # instance only counts as a real sandbox when its guarded constructor ran
    # (sets _sandbox_attested). An unattested instance -- only constructible
    # by bypassing __init__ -- is honestly labeled dev-only.
    real_attested = (isinstance(backend, RealSandboxBackend)
                     and getattr(backend, "_sandbox_attested", False))
    dev_only = 1 if (result.get("dev_only") or
                     (isinstance(backend, RealSandboxBackend) and not real_attested)) else 0

    # Primary key (review finding 1): random 48-bit suffix, NOT a
    # millisecond timestamp -- two calls in the same millisecond must never
    # collide and crash the API with IntegrityError.
    install_id = "inst-%s" % uuid.uuid4().hex[:12]
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO installs (install_id, app_id, installer, sha256, "
            "install_args, status, detail, dev_only, created_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (install_id, app, str(path), _sha256_of_file(path),
             json.dumps(args), status, json.dumps(result, default=str)[:4000],
             dev_only, _utcnow()),
        )
        conn.commit()
    finally:
        conn.close()

    _log_event("lab", "install %s: %s" % (status, app),
               {"app_id": app, "installer_sha256": _sha256_of_file(path)[:16],
                "dev_only": bool(dev_only)})

    out = {"status": status, "app_id": app, "install_id": install_id,
           "installer_sha256": _sha256_of_file(path), "dev_only": bool(dev_only),
           "detail": result}
    if dev_only:
        out["warning"] = ("dev/test backend was used; this install was NOT "
                          "isolated and must not feed a production verdict")
    return out


def _run_command_step(step: dict, dev_host: bool) -> tuple[str, dict, float]:
    command = step.get("command")
    if not isinstance(command, list) or not command:
        return "fail", {"error": "'command' step needs a non-empty command list"}, 0.0
    timeout = float(step.get("timeout_s", 60))
    started = time.time()
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=timeout)
        out = (proc.stdout or "")[-2000:]
        err = (proc.stderr or "")[-2000:]
        evidence = {"exit_code": proc.returncode, "stdout_tail": out,
                    "stderr_tail": err, "dev_host": dev_host}
        return ("pass" if proc.returncode == 0 else "fail"), evidence, time.time() - started
    except subprocess.TimeoutExpired:
        return "fail", {"error": "timeout after %ss" % timeout, "dev_host": dev_host}, timeout
    except FileNotFoundError:
        return "fail", {"error": "executable not found: %s" % command[0],
                        "dev_host": dev_host}, time.time() - started
    except Exception as exc:
        return "fail", {"error": "%s: %s" % (type(exc).__name__, exc),
                        "dev_host": dev_host}, time.time() - started


def _run_file_exists_step(step: dict) -> tuple[str, dict, float]:
    started = time.time()
    p = os.path.expanduser(str(step.get("path", "")))
    exists = os.path.exists(p)
    return ("pass" if exists else "fail"), {"path": p, "exists": exists}, time.time() - started


def _run_http_ok_step(step: dict) -> tuple[str, dict, float]:
    """Real HTTP check (urllib, stdlib). No fabricated responses."""
    started = time.time()
    url = str(step.get("url", ""))
    timeout = float(step.get("timeout_s", 10))
    if not url.startswith(("http://", "https://")):
        return "fail", {"error": "url must start with http:// or https://"}, 0.0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "genesis-lab/1.0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
        return ("pass" if code == 200 else "fail"), \
               {"url": url, "http_status": code}, time.time() - started
    except Exception as exc:
        return "fail", {"url": url, "error": "%s: %s" % (type(exc).__name__, exc)}, \
               time.time() - started


def run_tests(app_id, test_plan, backend=None) -> dict:
    """Run a test plan against an installed app and record results.

    test_plan = {"tests": [{"name": str,
                            "kind": "command" | "file_exists" | "http_ok",
                            "command": [...], "timeout_s": 60,   # command
                            "path": "...",                        # file_exists
                            "url": "https://...", "timeout_s": 10 # http_ok
                            }, ...]}

    On Windows with the real backend, "command" steps run inside the sandbox.
    On other platforms (or with MockSandboxBackend) they run on the dev host
    and are honestly marked dev_host=True in the evidence.

    Returns {"status": "completed", "passed": n, "failed": m, "results": [...]}.
    """
    if not app_id or not isinstance(app_id, str):
        return {"status": "error", "reason": "app_id must be a non-empty string"}
    tests = (test_plan or {}).get("tests")
    if not isinstance(tests, list) or not tests:
        return {"status": "error", "reason": "test_plan needs a non-empty 'tests' list"}

    if backend is None:
        try:
            backend = _default_backend()
        except SandboxUnavailableError:
            backend = None  # dev-host execution, marked honestly below
    # Attestation-based dev-host detection (review finding 2): a backend only
    # counts as a real sandbox if it is a RealSandboxBackend instance whose
    # guarded constructor ran (sets _sandbox_attested). Class identity alone
    # is not trusted: RealSandboxBackend is final (__init_subclass__ refuses
    # subclassing, so the guards cannot be skipped that way), and an instance
    # built without the constructor (e.g. via __new__) carries no attestation
    # and is treated as dev-host.
    dev_host = not (isinstance(backend, RealSandboxBackend)
                    and getattr(backend, "_sandbox_attested", False))

    # Primary key (review finding 1): random 48-bit suffix, NOT a
    # millisecond timestamp -- same-millisecond calls must never collide.
    run_id = "run-%s" % uuid.uuid4().hex[:12]
    plan_hash = hashlib.sha256(json.dumps(test_plan, sort_keys=True).encode()).hexdigest()[:16]
    results = []
    passed = failed = 0

    for step in tests:
        name = str(step.get("name", "unnamed"))
        kind = str(step.get("kind", ""))
        if kind == "command" and not dev_host:
            t0 = time.time()
            try:
                raw = backend.run(step["command"])
                ok = raw.get("status") == "ok" and raw.get("exit_code", 1) == 0
                result, evidence, dur = ("pass" if ok else "fail"), \
                    {"sandbox": True, "raw": json.dumps(raw, default=str)[:2000]}, \
                    time.time() - t0
            except Exception as exc:
                result, evidence, dur = "fail", {"error": "%s: %s" % (type(exc).__name__, exc)}, 0.0
        elif kind == "command":
            result, evidence, dur = _run_command_step(step, dev_host=True)
        elif kind == "file_exists":
            result, evidence, dur = _run_file_exists_step(step)
        elif kind == "http_ok":
            result, evidence, dur = _run_http_ok_step(step)
        else:
            result, evidence, dur = "fail", {"error": "unknown test kind: %r" % kind}, 0.0

        if result == "pass":
            passed += 1
        else:
            failed += 1
        results.append({"name": name, "kind": kind, "result": result,
                        "evidence": evidence, "duration_s": round(dur, 3)})

    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO test_runs (run_id, app_id, plan_hash, passed, failed, "
            "dev_host, created_utc) VALUES (?,?,?,?,?,?,?)",
            (run_id, app_id, plan_hash, passed, failed, int(dev_host), _utcnow()),
        )
        for i, r in enumerate(results):
            conn.execute(
                "INSERT INTO test_results (result_id, run_id, name, kind, result, "
                "evidence, duration_s) VALUES (?,?,?,?,?,?,?)",
                ("%s-%d" % (run_id, i), run_id, r["name"], r["kind"], r["result"],
                 json.dumps(r["evidence"], default=str)[:4000], r["duration_s"]),
            )
        conn.commit()
    finally:
        conn.close()

    _log_event("lab", "tests completed for %s: %d pass / %d fail" % (app_id, passed, failed),
               {"app_id": app_id, "run_id": run_id, "dev_host": dev_host})

    out = {"status": "completed", "app_id": app_id, "run_id": run_id,
           "passed": passed, "failed": failed, "results": results,
           "dev_host": dev_host}
    if dev_host:
        out["warning"] = ("tests ran on the dev host (no real sandbox on this "
                          "platform); verdict is provisional")
    return out


def verdict(app_id) -> dict:
    """Compute the verdict for an app from its latest test run.

    Rules: no test data -> WARN; any failed test -> FAIL; all passed -> PASS.
    A dev-host run can never yield a clean PASS: it yields WARN with the reason
    recorded, because it was not run in a real sandbox.
    """
    if not app_id or not isinstance(app_id, str):
        return {"status": "error", "reason": "app_id must be a non-empty string"}
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT run_id, passed, failed, dev_host, created_utc FROM test_runs "
            "WHERE app_id = ? ORDER BY created_utc DESC LIMIT 1", (app_id,)
        ).fetchone()
        if row is None:
            return {"status": "ok", "verdict": "WARN", "app_id": app_id,
                    "reason": "no test data recorded for this app",
                    "evidence": []}
        run_id, passed, failed, dev_host, created = row
        ev_rows = conn.execute(
            "SELECT name, kind, result, evidence, duration_s FROM test_results "
            "WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    evidence = [{"test": n, "kind": k, "result": r,
                 "evidence": json.loads(e), "duration_s": d}
                for n, k, r, e, d in ev_rows]

    if failed > 0:
        v, reason = "FAIL", "%d test(s) failed" % failed
    elif dev_host:
        v, reason = "WARN", ("latest run executed on dev host, not in a real "
                             "sandbox; verdict is provisional")
    else:
        v, reason = "PASS", "all %d test(s) passed in sandbox" % passed

    return {"status": "ok", "verdict": v, "app_id": app_id, "run_id": run_id,
            "passed": passed, "failed": failed, "reason": reason,
            "tested_utc": created, "evidence": evidence}


def report(app_id, lang="en") -> str:
    """Render a Markdown verdict report for father (returned as a string).

    lang="en" (default) or "fa" (Persian report body; code stays English).
    """
    v = verdict(app_id)
    fa = (lang == "fa")

    if v.get("status") != "ok":
        return "# %s\n\n%s: %s\n" % (
            "گزارش آزمایشگاه GENESIS" if fa else "GENESIS Lab Report",
            "خطا" if fa else "Error", v.get("reason", "unknown"))

    conn = _connect()
    try:
        inst = conn.execute(
            "SELECT installer, sha256, status, created_utc, dev_only FROM installs "
            "WHERE app_id = ? ORDER BY created_utc DESC LIMIT 1", (app_id,)
        ).fetchone()
    finally:
        conn.close()

    L = {
        "title": "گزارش آزمایشگاه GENESIS" if fa else "GENESIS Lab Report",
        "app": "برنامه" if fa else "Application",
        "verdict": "نتیجه" if fa else "Verdict",
        "reason": "دلیل" if fa else "Reason",
        "install": "نصب" if fa else "Installation",
        "installer": "فایل نصب" if fa else "Installer",
        "sha": "اثرانگشت SHA-256" if fa else "SHA-256",
        "istatus": "وضعیت نصب" if fa else "Install status",
        "when": "زمان" if fa else "When",
        "tests": "آزمون‌ها" if fa else "Tests",
        "tname": "نام" if fa else "Name",
        "tkind": "نوع" if fa else "Kind",
        "tres": "نتیجه" if fa else "Result",
        "tdur": "مدت (ثانیه)" if fa else "Duration (s)",
        "pass": "قبول" if fa else "PASS",
        "fail": "مردود" if fa else "FAIL",
        "warn": "هشدار" if fa else "WARN",
        "evidence": "شواهد" if fa else "Evidence",
        "gen": "تولیدشده در" if fa else "Generated",
        "devnote": ("این اجرا روی دستگاه توسعه انجام شد، نه در سندباکس واقعی."
                    if fa else
                    "This run executed on the dev host, not in a real sandbox."),
    }

    lines = ["# %s" % L["title"], "",
             "- **%s:** `%s`" % (L["app"], app_id),
             "- **%s:** **%s**" % (L["verdict"], L[v["verdict"].lower()]),
             "- **%s:** %s" % (L["reason"], v["reason"]), ""]
    lines += ["## %s" % L["install"], ""]
    if inst:
        installer, sha, istatus, when, dev_only = inst
        lines += ["- **%s:** `%s`" % (L["installer"], installer),
                  "- **%s:** `%s`" % (L["sha"], sha),
                  "- **%s:** %s" % (L["istatus"], istatus),
                  "- **%s:** %s" % (L["when"], when)]
        if dev_only:
            lines += ["", "> %s" % L["devnote"]]
    else:
        lines += ["- %s" % ("ثبتی وجود ندارد" if fa else "no install record")]
    lines += ["", "## %s" % L["tests"], "",
              "| %s | %s | %s | %s |" % (L["tname"], L["tkind"], L["tres"], L["tdur"]),
              "|---|---|---|---|"]
    for ev in v["evidence"]:
        res = L["pass"] if ev["result"] == "pass" else L["fail"]
        lines.append("| %s | %s | %s | %s |" %
                     (ev["test"], ev["kind"], res, ev["duration_s"]))
    lines += ["", "## %s" % L["evidence"], ""]
    for ev in v["evidence"]:
        lines.append("- **%s** (%s): `%s`" %
                     (ev["test"], ev["result"],
                      json.dumps(ev["evidence"], default=str)[:300]))
    lines += ["", "_%s: %s_" % (L["gen"], _utcnow()), ""]
    return "\n".join(lines) + "\n"
