"""Windows Sandbox isolation for the GENESIS hands module.

Risky (risk=high) steps MUST be executed through run_isolated() when the
sandbox is available; hands.py enforces that routing.

Platform truth:
- is_available() -> True only on Windows with WindowsSandbox.exe present.
- run_isolated() RAISES RuntimeError on non-Windows (honest platform guard),
  never pretends to sandbox.
- The sandbox-execution path itself is Windows-only code and was not live-tested
  during development (no Windows host); guards and payload construction are
  mock-tested. See BUILDER_NOTES.md.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path

_IS_WINDOWS = platform.system() == "Windows"


def is_available() -> bool:
    """True when this host can run Windows Sandbox."""
    if not _IS_WINDOWS:
        return False
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    sandbox_exe = Path(system_root) / "System32" / "WindowsSandbox.exe"
    return sandbox_exe.exists()


def _command_line(command: list) -> str:
    """Convert a command list to a Windows command line (sandbox side)."""
    if not command or not all(isinstance(part, str) for part in command):
        raise ValueError("command must be a non-empty list of strings")
    return subprocess.list2cmdline(command)


def run_isolated(command: list, timeout_s: float = 300.0) -> dict:
    """Run a command inside Windows Sandbox and return its result.

    Returns a dict with "status": "ok" | "error", plus "returncode",
    "stdout", "stderr" on success. Raises RuntimeError on non-Windows.
    """
    if not _IS_WINDOWS:
        raise RuntimeError(
            "run_isolated requires Windows Sandbox: "
            f"this host runs {platform.system()}, not Windows."
        )
    if not is_available():
        return {
            "status": "error",
            "reason": "sandbox_unavailable",
            "detail": "WindowsSandbox.exe not found on this machine.",
            "sandboxed": False,
        }

    cmdline = _command_line(command)
    with tempfile.TemporaryDirectory(prefix="genesis_sandbox_") as workdir:
        share = Path(workdir)
        runner = share / "run.cmd"
        runner.write_text(
            textwrap.dedent(
                f"""\
                @echo off
                cd /d C:\\SandboxShare
                {cmdline} > stdout.txt 2> stderr.txt
                echo %ERRORLEVEL% > exitcode.txt
                shutdown /s /t 1
                """
            ),
            encoding="utf-8",
        )
        config = share / "genesis.wsb"
        config.write_text(
            textwrap.dedent(
                f"""\
                <Configuration>
                  <MappedFolders>
                    <MappedFolder>
                      <HostFolder>{share}</HostFolder>
                      <SandboxFolder>C:\\SandboxShare</SandboxFolder>
                      <ReadOnly>false</ReadOnly>
                    </MappedFolder>
                  </MappedFolders>
                  <LogonCommand>
                    <Command>cmd /c C:\\SandboxShare\\run.cmd</Command>
                  </LogonCommand>
                </Configuration>
                """
            ),
            encoding="utf-8",
        )

        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        sandbox_exe = str(Path(system_root) / "System32" / "WindowsSandbox.exe")
        started = time.monotonic()
        try:
            subprocess.run(
                [sandbox_exe, str(config)],
                timeout=timeout_s,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "reason": "sandbox_timeout",
                "detail": f"sandbox did not finish within {timeout_s}s.",
                "sandboxed": True,
            }

        def _read(name: str) -> str:
            try:
                return (share / name).read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
            except OSError:
                return ""

        exitcode_raw = _read("exitcode.txt")
        elapsed = time.monotonic() - started
        if not exitcode_raw:
            return {
                "status": "error",
                "reason": "result_file_missing",
                "detail": (
                    "sandbox finished but produced no exit-code file; "
                    "the command may not have run."
                ),
                "sandboxed": True,
                "elapsed_s": round(elapsed, 2),
            }
        try:
            returncode = int(exitcode_raw)
        except ValueError:
            returncode = -1
        return {
            "status": "ok",
            "returncode": returncode,
            "stdout": _read("stdout.txt"),
            "stderr": _read("stderr.txt"),
            "sandboxed": True,
            "elapsed_s": round(elapsed, 2),
        }
