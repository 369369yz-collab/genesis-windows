"""genesis-scheduler: SCHEDULED TASKS module for the GENESIS Windows AI assistant.

Public API (all return plain dicts with a "status" key):
    schedule(name, trigger, action, overwrite=False)
    unschedule(name)
    list_jobs()
    morning_news(time_str="07:00", name="morning_news")
    reminder(name, time_str, message)

Trigger dict shapes:
    {"type": "daily",    "time": "HH:MM"}
    {"type": "weekly",   "days": ["mon","wed"], "time": "HH:MM"}
    {"type": "once",     "at": "YYYY-MM-DDTHH:MM"}
    {"type": "interval", "minutes": N}

Action dict shapes:
    {"kind": "command", "command": [...], "workdir": "<optional>"}
    {"kind": "message", "title": "<optional>", "text": "..."}

On Windows the SchtasksBackend wraps `schtasks.exe` for real scheduling.
On other platforms a DevBackend stores jobs in JSON and marks them
dev_only=True: it never pretends jobs will actually fire. All Windows-only
code paths raise an honest SchedulerError on other platforms.
schtasks call failures (timeout, spawn errors, undecodable output) return the
standard {"status": "error", "reason": ...} dict — a raw exception never escapes.

Code is 100% technical English. Zero spend. No credentials anywhere.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MODULE_NAME = "genesis-scheduler"
MODULE_VERSION = "1.0.0"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,63}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_WEEKDAYS = {"mon": "MON", "tue": "TUE", "wed": "WED",
             "thu": "THU", "fri": "FRI", "sat": "SAT", "sun": "SUN"}


class SchedulerError(RuntimeError):
    """Base error for genesis-scheduler."""


# ---------------------------------------------------------------------------
# Data directory + dev store
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    env = os.environ.get("GENESIS_SCHEDULER_DATA_DIR")
    d = Path(env) if env else Path.home() / ".genesis" / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dev_store_path() -> Path:
    return _data_dir() / "jobs.json"


def _load_dev_jobs() -> dict:
    p = _dev_store_path()
    if not p.is_file():
        return {}
    try:
        jobs = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        # Undecodable bytes (UnicodeDecodeError is NOT a JSONDecodeError
        # subclass) and unreadable/corrupt files degrade to an empty store —
        # a raw exception must never escape the public dict contract.
        return {}
    # A corrupted store can hold valid JSON that is not a dict (partial
    # interleaved write or hand-edited file); degrade the same way rather
    # than letting TypeError/AttributeError escape from callers.
    if not isinstance(jobs, dict):
        return {}
    return jobs


def _save_dev_jobs(jobs: dict) -> None:
    _dev_store_path().write_text(json.dumps(jobs, indent=2, ensure_ascii=False),
                                 encoding="utf-8")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_name(name) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SchedulerError(
            "job name must match %s (got %r)" % (_NAME_RE.pattern, name))
    return name


def _validate_time(time_str) -> str:
    if not isinstance(time_str, str) or not _TIME_RE.match(time_str):
        raise SchedulerError("time must be HH:MM 24h (got %r)" % (time_str,))
    return time_str


def _validate_trigger(trigger: dict) -> dict:
    if not isinstance(trigger, dict):
        raise SchedulerError("trigger must be a dict")
    ttype = trigger.get("type")
    if ttype == "daily":
        _validate_time(trigger.get("time"))
    elif ttype == "weekly":
        days = trigger.get("days")
        if not isinstance(days, list) or not days or \
                any(d not in _WEEKDAYS for d in days):
            raise SchedulerError("weekly trigger needs days subset of %s"
                                 % sorted(_WEEKDAYS))
        _validate_time(trigger.get("time"))
    elif ttype == "once":
        at = trigger.get("at")
        try:
            datetime.strptime(at, "%Y-%m-%dT%H:%M")
        except (TypeError, ValueError):
            raise SchedulerError("once trigger needs at='YYYY-MM-DDTHH:MM' "
                                 "(got %r)" % (at,))
    elif ttype == "interval":
        minutes = trigger.get("minutes")
        if not isinstance(minutes, int) or minutes < 1:
            raise SchedulerError("interval trigger needs minutes>=1 int")
    else:
        raise SchedulerError("unknown trigger type: %r" % (ttype,))
    return trigger


def _validate_action(action: dict) -> dict:
    if not isinstance(action, dict):
        raise SchedulerError("action must be a dict")
    kind = action.get("kind")
    if kind == "command":
        cmd = action.get("command")
        if not isinstance(cmd, list) or not cmd or \
                not all(isinstance(c, str) for c in cmd):
            raise SchedulerError("command action needs a non-empty list of str")
    elif kind == "message":
        text = action.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SchedulerError("message action needs non-empty text")
        if len(text) > 500:
            raise SchedulerError("message text too long (max 500 chars)")
    else:
        raise SchedulerError("unknown action kind: %r" % (kind,))
    return action


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _quote_cmd(command: list) -> str:
    """Build a schtasks /TR command line from a command list.

    Uses subprocess.list2cmdline, which quotes per the MSVC command-line
    rules (the parsing every C-runtime program, including python.exe,
    applies): arguments with spaces/metacharacters are double-quoted,
    inner quotes become \\", backslashes before quotes are doubled.

    Percent signs are passed through VERBATIM on purpose. Task Scheduler
    launches /TR via CreateProcess, which performs NO %VAR% expansion, so
    doubling % would corrupt argv (a reminder text "50% off" would arrive
    as "50%% off"). Residual risk, stated honestly: if a command action
    routes through cmd.exe itself (e.g. ["cmd", "/c", ...]), cmd WILL
    expand %VAR% at task time — that is cmd's documented behavior and the
    caller's responsibility (double the % yourself in that case).
    """
    return subprocess.list2cmdline([str(c) for c in command])


# All GENESIS tasks live under this Task Scheduler folder so they can never
# collide with OS or third-party tasks sharing a bare name.
_TASK_FOLDER = "\\GENESIS"


def _task_path(name: str) -> str:
    return "%s\\%s" % (_TASK_FOLDER, name)


class SchtasksBackend:
    """Production backend: wraps Windows schtasks.exe."""

    BACKEND = "schtasks"

    def __init__(self):
        if platform.system() != "Windows":
            raise SchedulerError(
                "schtasks backend requires Windows; current platform is '%s'. "
                "On other platforms the dev backend stores jobs without "
                "executing them." % platform.system())
        if not _which_schtasks():
            raise SchedulerError("schtasks.exe not found on PATH")

    def _exists(self, task_path: str) -> bool:
        # Pre-query is a fast path only; on any call failure we report
        # "unknown" as False. The caller's /Create then raises through the
        # same guard and returns the honest error dict — never a false
        # "not exists" followed by a raw exception.
        try:
            rc, _, _ = _run_schtasks(["schtasks", "/Query", "/TN", task_path])
        except _SCHTASKS_CALL_ERRORS:
            return False
        return rc == 0

    def schedule(self, name, trigger, action, overwrite=False) -> dict:
        """Create (or replace) a scheduled job.

        Concurrency semantics (enforced at the schtasks layer): concurrent
        schedule() calls with the same name and overwrite=False -> exactly
        one wins ("scheduled"), the rest get "already_exists". The
        pre-query _exists() check below is only a fast path for the common
        sequential case; enforcement comes from OMITTING /F when
        overwrite=False, so a raced duplicate fails loudly at the schtasks
        level instead of silently replacing the winner's task. The failure
        is translated to "already_exists" (never a crash, never a false
        "scheduled").
        """
        task_path = _task_path(name)
        if not overwrite and self._exists(task_path):
            return {"status": "already_exists", "name": name,
                    "task_path": task_path,
                    "hint": "pass overwrite=True to replace"}
        # /F is passed ONLY for a deliberate overwrite=True replace. A
        # genuinely new task needs no force flag, and passing it here would
        # let a raced duplicate silently replace the winner.
        args = ["schtasks", "/Create", "/TN", task_path]
        if overwrite:
            args.append("/F")
        args += ["/TR", _quote_cmd(_action_to_command(action))]
        t = trigger["type"]
        if t == "daily":
            args += ["/SC", "DAILY", "/ST", trigger["time"]]
        elif t == "weekly":
            args += ["/SC", "WEEKLY",
                     "/D", ",".join(_WEEKDAYS[d] for d in trigger["days"]),
                     "/ST", trigger["time"]]
        elif t == "once":
            dt = datetime.strptime(trigger["at"], "%Y-%m-%dT%H:%M")
            # schtasks /SD parses per the machine locale; we emit US order and
            # say so explicitly (documented limitation, also in README).
            args += ["/SC", "ONCE", "/ST", dt.strftime("%H:%M"),
                     "/SD", dt.strftime("%m/%d/%Y")]
        elif t == "interval":
            args += ["/SC", "MINUTE", "/MO", str(trigger["minutes"])]
        rc, out, err = _guarded_schtasks(args)
        if rc is None:
            return {"status": "error", "reason": err, "name": name}
        if rc != 0:
            msg = err.strip() or out.strip()
            # Racy middle case: the pre-query said "not exists", but another
            # caller won the name before this /Create landed. Without /F,
            # schtasks rejects the duplicate — report it honestly as
            # already_exists, never a false "scheduled" and never a crash.
            if not overwrite and "already exist" in msg.lower():
                return {"status": "already_exists", "name": name,
                        "task_path": task_path,
                        "hint": "pass overwrite=True to replace"}
            return {"status": "error", "reason": msg, "name": name}
        return {"status": "scheduled", "name": name, "task_path": task_path,
                "backend": self.BACKEND, "trigger": trigger, "action": action,
                "date_format_note": "once-triggers use MM/DD/YYYY (US locale "
                                   "expected by schtasks /SD)"}

    def unschedule(self, name) -> dict:
        task_path = _task_path(name)
        rc, out, err = _guarded_schtasks(
            ["schtasks", "/Delete", "/TN", task_path, "/F"])
        if rc is None:
            return {"status": "error", "reason": err, "name": name}
        if rc != 0:
            msg = (err.strip() or out.strip()).lower()
            if "cannot find" in msg or "not exist" in msg:
                return {"status": "not_found", "name": name}
            return {"status": "error", "reason": err.strip() or out.strip(),
                    "name": name}
        return {"status": "unscheduled", "name": name, "backend": self.BACKEND}

    def list_jobs(self) -> dict:
        rc, out, err = _guarded_schtasks(
            ["schtasks", "/Query", "/FO", "CSV", "/NH"])
        if rc is None:
            return {"status": "error", "reason": err, "jobs": []}
        if rc != 0:
            return {"status": "error",
                    "reason": err.strip() or out.strip(), "jobs": []}
        jobs = []
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            # Only GENESIS-folder tasks are ours; the folder prefix is the
            # namespace that keeps OS tasks out of this list.
            if (len(parts) >= 3 and parts[0]
                    and parts[0].startswith(_TASK_FOLDER + "\\")):
                jobs.append({"name": parts[0][len(_TASK_FOLDER) + 1:],
                             "task_path": parts[0],
                             "next_run": parts[1], "status_text": parts[2],
                             "backend": self.BACKEND})
        return {"status": "ok", "backend": self.BACKEND, "jobs": jobs}


def _which_schtasks():
    from shutil import which
    return which("schtasks")


def _run_schtasks(args):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


# Exceptions that can escape _run_schtasks on a real host. The call is
# subprocess.run(args, capture_output=True, text=True, timeout=30) with
# check NOT set, so this list is provably complete for production:
#  - TimeoutExpired / plain TimeoutError: schtasks hung past the timeout.
#    TimeoutExpired is NOT a subclass of builtin TimeoutError, so both are
#    listed; SubprocessError (parent of TimeoutExpired) is also listed for
#    any other subprocess-layer failure (e.g. CalledProcessError from a
#    stub/callers that raise it).
#  - OSError: the spawn itself failed (FileNotFoundError when schtasks.exe
#    is missing, PermissionError when it is not executable).
#  - UnicodeDecodeError: with text=True, communicate() raises this when
#    schtasks stdout/stderr holds bytes undecodable in the locale encoding
#    (non-ANSI task names on non-English Windows, localized error text).
#    It is a subclass of ValueError; only the specific subclass is caught.
# Deliberately NOT caught:
#  - ValueError / TypeError from bad arguments: args are module-constructed
#    constants, so an argument error is a deterministic programmer bug that
#    must crash loudly in tests, never masquerade as a runtime scheduling
#    error.
#  - KeyboardInterrupt / BaseException: interrupts must always propagate.
_SCHTASKS_CALL_ERRORS = (TimeoutError, UnicodeDecodeError,
                         subprocess.SubprocessError, OSError)


def _schtasks_call_error(exc: BaseException) -> str:
    """Honest, human-readable reason for a failed schtasks call."""
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
        timeout = getattr(exc, "timeout", None)
        if timeout is not None:
            return "schtasks timed out after %ss" % timeout
        return "schtasks timed out (%s)" % exc
    if isinstance(exc, OSError):
        return "schtasks could not be started (OSError: %s)" % exc
    return "schtasks call failed (%s: %s)" % (type(exc).__name__, exc)


def _guarded_schtasks(args):
    """Call _run_schtasks and translate call-time exceptions.

    Returns (rc, out, err) for a completed call. If the call itself fails
    (timeout / spawn error), returns (None, "", reason) — rc=None signals
    the caller to return the standard {"status": "error", ...} dict instead
    of letting a raw exception escape the module's dict contract.
    """
    try:
        return _run_schtasks(args)
    except _SCHTASKS_CALL_ERRORS as exc:
        return None, "", _schtasks_call_error(exc)


class DevBackend:
    """Non-Windows dev backend: stores jobs in JSON, honestly dev_only.

    Jobs recorded here will NOT execute on this platform. Real execution
    requires Windows + schtasks.
    """

    BACKEND = "dev"

    def schedule(self, name, trigger, action) -> dict:
        # No subprocess calls exist in this backend. Storage failures are
        # fully contained: _load_dev_jobs degrades corrupt/undecodable JSON
        # (JSONDecodeError, UnicodeDecodeError, non-dict JSON) to {} and
        # _data_dir()/read OSErrors map to the standard error dict, so no
        # raw exception escapes this method. Thread-level JSON interleaving
        # is a known, self-healing dev-only trait (see module docstring) and
        # is NOT serialized here.
        try:
            jobs = _load_dev_jobs()
            jobs[name] = {"name": name, "trigger": trigger, "action": action,
                          "dev_only": True, "backend": self.BACKEND,
                          "note": "stored on non-Windows host; will NOT "
                                  "execute until created on Windows via "
                                  "schtasks"}
            _save_dev_jobs(jobs)
        except OSError as exc:
            return {"status": "error",
                    "reason": "dev store write failed (OSError: %s)" % exc,
                    "name": name}
        return {"status": "scheduled_dev", "name": name, "backend": self.BACKEND,
                "trigger": trigger, "action": action, "dev_only": True,
                "warning": "dev backend: job stored but will not run on this "
                           "platform"}

    def unschedule(self, name) -> dict:
        try:
            jobs = _load_dev_jobs()
            if name not in jobs:
                return {"status": "not_found", "name": name}
            del jobs[name]
            _save_dev_jobs(jobs)
        except OSError as exc:
            return {"status": "error",
                    "reason": "dev store write failed (OSError: %s)" % exc,
                    "name": name}
        return {"status": "unscheduled", "name": name, "backend": self.BACKEND}

    def list_jobs(self) -> dict:
        try:
            jobs = _load_dev_jobs()
        except OSError as exc:
            return {"status": "error",
                    "reason": "dev store read failed (OSError: %s)" % exc,
                    "backend": self.BACKEND, "jobs": []}
        return {"status": "ok", "backend": self.BACKEND,
                "jobs": list(jobs.values())}


def _default_backend():
    if platform.system() == "Windows":
        return SchtasksBackend()
    return DevBackend()


def _action_to_command(action: dict) -> list:
    """Resolve a message action to the reminder runner command."""
    if action["kind"] == "command":
        return list(action["command"])
    # kind == "message": run the bundled reminder script.
    script = str(Path(__file__).resolve().parent / "recipes" / "reminder.py")
    cmd = [sys.executable, script,
           "--title", action.get("title", "GENESIS"),
           "--message", action["text"]]
    return cmd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def schedule(name, trigger, action, overwrite=False) -> dict:
    """Create (or replace) a scheduled job. Returns a dict with "status".

    Raises SchedulerError on invalid name/trigger/action.

    Overwrite semantics: overwrite=False never replaces an existing job —
    sequentially (pre-query fast path) or concurrently (the schtasks layer
    rejects a raced duplicate create and it maps to "already_exists").
    overwrite=True replaces deliberately via schtasks /F.
    """
    _validate_name(name)
    _validate_trigger(trigger)
    _validate_action(action)
    backend = _default_backend()
    if not overwrite and isinstance(backend, DevBackend):
        # The pre-check touches the dev store (which creates the data dir);
        # an OSError from _data_dir() (e.g. GENESIS_SCHEDULER_DATA_DIR points
        # at an existing file) must map to the error dict, not escape raw.
        try:
            if name in _load_dev_jobs():
                return {"status": "already_exists", "name": name,
                        "hint": "pass overwrite=True to replace"}
        except OSError as exc:
            return {"status": "error",
                    "reason": "dev store read failed (OSError: %s)" % exc,
                    "name": name}
    if isinstance(backend, SchtasksBackend):
        return backend.schedule(name, trigger, action, overwrite=overwrite)
    return backend.schedule(name, trigger, action)


def unschedule(name) -> dict:
    """Delete a scheduled job. Returns {"status": "unscheduled"|"not_found"|"error"}."""
    _validate_name(name)
    return _default_backend().unschedule(name)


def list_jobs() -> dict:
    """List scheduled jobs. Returns {"status": "ok", "backend": ..., "jobs": [...]}."""
    return _default_backend().list_jobs()


# ---------------------------------------------------------------------------
# Built-in recipes
# ---------------------------------------------------------------------------

def _recipes_dir() -> Path:
    return Path(__file__).resolve().parent / "recipes"


def morning_news(time_str="07:00", name="morning_news") -> dict:
    """Recipe: every morning at time_str, fetch top headlines (free public RSS)
    and save a dated digest file. Zero spend, real HTTP fetch in the runner.

    Returns the schedule() result dict.
    """
    _validate_time(time_str)
    script = str(_recipes_dir() / "morning_news.py")
    try:
        out_dir = str(_data_dir() / "news")
    except OSError as exc:
        return {"status": "error",
                "reason": "data dir unavailable (OSError: %s)" % exc,
                "name": name}
    action = {"kind": "command",
              "command": [sys.executable, script, "--out-dir", out_dir]}
    return schedule(name, {"type": "daily", "time": time_str}, action)


def reminder(name, time_str, message) -> dict:
    """Recipe: daily reminder at time_str showing `message` in a Windows
    message box (via the bundled runner script; logs to file elsewhere).

    Returns the schedule() result dict.
    """
    _validate_name(name)
    _validate_time(time_str)
    if not isinstance(message, str) or not message.strip():
        raise SchedulerError("reminder message must be non-empty")
    action = {"kind": "message", "title": name, "text": message.strip()}
    return schedule(name, {"type": "daily", "time": time_str}, action)
