"""Execution engine for the GENESIS hands module.

execute(plan, on_ask=None) dispatches each plan step to the local backend
(pywinauto, Windows-only) or the web backend (Playwright, cross-platform).

Execution order per step is fixed:
    1. permission_gate.check() FIRST. "deny" -> the whole plan aborts.
       "ask" -> the on_ask callback decides; without a callback the step is
       denied (fail-closed). The callback receives (action, step) and must
       return True (proceed) or False (abort).
    2. risk == "high" -> route through Windows Sandbox first WHEN AVAILABLE.
       When the sandbox is not available the step runs in place, but the
       result records "sandboxed": False and "sandbox_available": False so
       nothing is silently claimed.
    3. Run the step on the chosen backend.

No network calls are made by this module: plans arrive from the network mind
through the bridge before execute() is called, and step results are returned
to the caller. The only bridge-adjacent surface is web automation, which
drives a real local browser — it never fabricates page data.
"""

from __future__ import annotations

import base64
import json
import platform
import sys
from typing import Callable

from genesis_hands import permission_gate, sandbox

_IS_WINDOWS = platform.system() == "Windows"

_LOCAL_MODES = ("local",)
_WEB_MODES = ("web",)

# ---------------------------------------------------------------------------
# Local backend (pywinauto, Windows-only)
# ---------------------------------------------------------------------------

_LOCAL_KINDS = ("type_text", "press_key", "click", "open_app", "close_app",
                "run_command")


def _local_backend(step: dict) -> dict:
    """Run one step via pywinauto. Windows-only; raises on other platforms."""
    if not _IS_WINDOWS:
        raise RuntimeError(
            "local backend requires Windows with pywinauto installed; "
            f"this host runs {platform.system()}."
        )
    try:
        from pywinauto import keyboard, mouse
        from pywinauto.application import Application
    except ImportError as exc:
        return {
            "status": "error",
            "reason": "pywinauto_not_installed",
            "detail": str(exc),
        }

    kind = step["kind"]
    target = step.get("target", "")
    params = step.get("params", {}) or {}

    try:
        if kind == "type_text":
            keyboard.send_keys(str(params.get("text", "")), with_spaces=True)
            return {"status": "ok", "kind": kind}
        if kind == "press_key":
            keyboard.send_keys(str(params.get("key", target)))
            return {"status": "ok", "kind": kind}
        if kind == "click":
            x = params.get("x")
            y = params.get("y")
            if x is not None and y is not None:
                mouse.click(coords=(int(x), int(y)))
            else:
                mouse.click()
            return {"status": "ok", "kind": kind}
        if kind == "open_app":
            Application().start(target)
            return {"status": "ok", "kind": kind}
        if kind == "close_app":
            app = Application().connect(title=str(target))
            app.kill()
            return {"status": "ok", "kind": kind}
        if kind == "run_command":
            import subprocess

            command = params.get("command")
            if not command or not isinstance(command, list):
                return {"status": "error", "reason": "bad_params",
                        "detail": "run_command needs params.command as a list"}
            timeout = float(params.get("timeout_s", 60))
            completed = subprocess.run(command, capture_output=True,
                                       text=True, timeout=timeout)
            return {
                "status": "ok" if completed.returncode == 0 else "error",
                "kind": kind,
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            }
        return {"status": "error", "reason": "unknown_local_kind",
                "detail": f"local backend has no kind {kind!r}"}
    except Exception as exc:  # backend failure -> honest error, not a crash
        return {"status": "error", "reason": "backend_exception",
                "detail": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Web backend (Playwright, cross-platform)
# ---------------------------------------------------------------------------

_WEB_KINDS = ("goto", "click", "fill", "type", "press", "wait",
              "screenshot", "extract_text")


class _WebSession:
    """Holds one Playwright browser/page across the steps of a web plan."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None

    def open(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page()

    def close(self):
        for resource in (self._browser, self._playwright):
            try:
                if resource is not None:
                    resource.close()
            except Exception:
                pass
        self._browser = None
        self._page = None
        self._playwright = None

    def run(self, step: dict) -> dict:
        page = self._page
        kind = step["kind"]
        target = step.get("target", "")
        params = step.get("params", {}) or {}
        if kind == "goto":
            page.goto(str(target), timeout=int(params.get("timeout_ms", 30000)))
            return {"status": "ok", "kind": kind, "url": page.url}
        if kind == "click":
            page.click(str(params.get("selector", target)))
            return {"status": "ok", "kind": kind}
        if kind == "fill":
            page.fill(str(params.get("selector", target)),
                      str(params.get("text", "")))
            return {"status": "ok", "kind": kind}
        if kind == "type":
            page.type(str(params.get("selector", target)),
                      str(params.get("text", "")))
            return {"status": "ok", "kind": kind}
        if kind == "press":
            page.press(str(params.get("selector", target)),
                       str(params.get("key", target)))
            return {"status": "ok", "kind": kind}
        if kind == "wait":
            page.wait_for_timeout(int(float(params.get("seconds", 1)) * 1000))
            return {"status": "ok", "kind": kind}
        if kind == "screenshot":
            path = params.get("path")
            shot = page.screenshot(path=path)
            return {"status": "ok", "kind": kind,
                    "bytes": len(shot), "path": path}
        if kind == "extract_text":
            selector = params.get("selector")
            text = (page.inner_text(selector) if selector
                    else page.content())
            return {"status": "ok", "kind": kind,
                    "text": text[:20000]}
        return {"status": "error", "reason": "unknown_web_kind",
                "detail": f"web backend has no kind {kind!r}"}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OnAsk = Callable[[dict, dict], bool]


def _encode_step(step: dict) -> str:
    payload = json.dumps(step, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _run_high_risk_isolated(step: dict) -> dict:
    """Execute a high-risk step inside Windows Sandbox; returns step result."""
    encoded = _encode_step(step)
    inner = [sys.executable, "-m", "genesis_hands.step_runner", encoded]
    iso = sandbox.run_isolated(inner, timeout_s=float(
        (step.get("params") or {}).get("timeout_s", 300)))
    if iso.get("status") != "ok":
        return {"status": "error", "kind": step["kind"],
                "reason": "sandbox_execution_failed", "sandbox": iso,
                "sandboxed": True}
    stdout = iso.get("stdout", "")
    try:
        result = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        result = {"status": "error", "reason": "sandbox_bad_output",
                  "detail": "sandbox ran but produced no parseable result"}
    result = dict(result)
    result["sandboxed"] = True
    return result


def run_single_step(step: dict) -> dict:
    """Run one already-gated step on its backend (no gate applied here)."""
    mode = step.get("mode", "local")
    if mode == "local":
        if step["kind"] not in _LOCAL_KINDS:
            return {"status": "error", "reason": "kind_not_supported",
                    "detail": f"{step['kind']!r} is not a local kind"}
        try:
            return _local_backend(step)
        except RuntimeError as exc:  # honest Windows-only guard
            return {"status": "error", "reason": "platform_not_windows",
                    "detail": str(exc)}
    if mode == "web":
        if step["kind"] not in _WEB_KINDS:
            return {"status": "error", "reason": "kind_not_supported",
                    "detail": f"{step['kind']!r} is not a web kind"}
        session = _WebSession()
        try:
            session.open()
        except ImportError as exc:
            return {"status": "error", "reason": "playwright_not_installed",
                    "detail": str(exc)}
        except Exception as exc:
            return {"status": "error", "reason": "browser_launch_failed",
                    "detail": f"{type(exc).__name__}: {exc}"}
        try:
            return session.run(step)
        except Exception as exc:
            return {"status": "error", "reason": "backend_exception",
                    "detail": f"{type(exc).__name__}: {exc}"}
        finally:
            session.close()
    return {"status": "error", "reason": "unknown_mode",
            "detail": f"mode must be 'local' or 'web', got {mode!r}"}


def _validate_plan(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("plan must be a dict")
    mode = plan.get("mode")
    if mode not in ("local", "web"):
        raise ValueError("plan['mode'] must be 'local' or 'web'")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("plan['steps'] must be a non-empty list")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {index} must be a dict")
        for field in ("kind", "target", "risk"):
            if field not in step:
                raise ValueError(f"step {index} is missing '{field}'")
        if step["risk"] not in ("low", "medium", "high"):
            raise ValueError(f"step {index} has invalid risk")
        step["mode"] = mode
    return plan


def _gate_action_for_step(step: dict) -> dict:
    """Build the gate action for a step, including the REAL payload.

    For run_command the never-tier rules must see the actual argv
    (params.command), not the human label in "target" — otherwise a
    destructive command hides behind an innocent target string.
    """
    action = {"kind": step["kind"], "target": step["target"],
              "risk": step["risk"]}
    if step["kind"] == "run_command":
        params = step.get("params") or {}
        command = params.get("command")
        if isinstance(command, list):
            action["command_text"] = " ".join(str(c) for c in command)
        elif command is not None:
            action["command_text"] = str(command)
    return action


def execute(plan: dict, on_ask: OnAsk | None = None) -> dict:
    """Execute a plan, step by step, behind the permission gate.

    plan = {"mode": "local"|"web",
            "steps": [{"kind", "target", "risk", "params"?}, ...]}

    Returns {"status": "completed"|"aborted", "results": [...], ...}.
    A denied step (or an "ask" step with no approving on_ask) aborts the plan;
    already-completed steps are reported so the caller can see the cut point.
    """
    plan = _validate_plan(plan)
    results: list[dict] = []

    if plan["mode"] == "web":
        session: _WebSession | None = _WebSession()
        try:
            session.open()
        except ImportError as exc:
            return {"status": "aborted", "reason": "playwright_not_installed",
                    "detail": str(exc), "results": []}
        except Exception as exc:  # e.g. browser binary missing
            return {"status": "aborted", "reason": "browser_launch_failed",
                    "detail": f"{type(exc).__name__}: {exc}", "results": []}
    else:
        session = None

    try:
        for index, step in enumerate(plan["steps"]):
            # The gate sees the real payload (command_text for run_command),
            # and the approver sees the full step including params.
            action = _gate_action_for_step(step)
            verdict = permission_gate.check(action)

            if verdict == "deny":
                results.append({"step": index, "kind": step["kind"],
                                "verdict": "deny", "executed": False})
                return {"status": "aborted", "reason": "step_denied",
                        "step_index": index, "results": results}
            if verdict == "ask":
                approved = on_ask(action, step) if on_ask else False
                if not approved:
                    results.append({"step": index, "kind": step["kind"],
                                    "verdict": "ask", "approved": False,
                                    "executed": False})
                    return {"status": "aborted", "reason": "step_not_approved",
                            "step_index": index, "results": results}

            if step["risk"] == "high" and sandbox.is_available():
                # Sandbox path already gated above; step_runner applies no gate.
                step_result = _run_high_risk_isolated(step)
            elif step["risk"] == "high":
                step_result = run_single_step(step)
                step_result = dict(step_result)
                step_result["sandboxed"] = False
                step_result["sandbox_available"] = False
                step_result["sandbox_note"] = (
                    "high-risk step ran in place: Windows Sandbox is not "
                    "available on this host.")
            else:
                if session is not None:
                    try:
                        step_result = session.run(step)
                    except Exception as exc:
                        step_result = {"status": "error",
                                       "reason": "backend_exception",
                                       "detail": f"{type(exc).__name__}: {exc}"}
                else:
                    step_result = run_single_step(step)

            results.append({"step": index, "kind": step["kind"],
                            "verdict": verdict,
                            "executed": True, "result": step_result})
            if step_result.get("status") != "ok":
                return {"status": "aborted",
                        "reason": "step_failed", "step_index": index,
                        "results": results}
        return {"status": "completed", "results": results}
    finally:
        if session is not None:
            session.close()
