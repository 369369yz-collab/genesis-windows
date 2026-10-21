#!/usr/bin/env python3
"""reminder runner: show a reminder message.

On Windows it shows a small AUTO-DISMISSING toast via WScript.Shell.Popup
(stdlib subprocess + wscript, no extra modules); if wscript is unavailable
it falls back to a blocking MessageBoxW and says so honestly.
On any platform it also appends the reminder to reminders.log in the
scheduler data dir, so nothing is silently lost. reminders.log is the
toast feed the avatar host's summoned-layer renderer consumes (see
UI_SURFACE.md) — this module builds no panels.

Invoked by the genesis-scheduler reminder recipe.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Toast auto-dismiss timeout on Windows, seconds.
TOAST_TIMEOUT_SECONDS = 20


def _data_dir() -> Path:
    env = os.environ.get("GENESIS_SCHEDULER_DATA_DIR")
    d = Path(env) if env else Path.home() / ".genesis" / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _vbs_string(s: str) -> str:
    """Encode a Python string as a VBScript string literal."""
    parts = str(s).replace('"', '""').split("\n")
    return '"' + '" & vbCrLf & "'.join(parts) + '"'


def _show_toast_windows(title: str, message: str) -> tuple:
    """Show a small auto-dismissing toast on Windows.

    Primary: WScript.Shell.Popup with a timeout (auto-dismisses, no click
    needed). Fallback: blocking MessageBoxW, reported honestly in `method`.
    Returns (shown: bool, method: str).
    """
    vbs = ("CreateObject(\"WScript.Shell\").Popup(%s, %d, %s, 64)"
           % (_vbs_string(message), TOAST_TIMEOUT_SECONDS,
              _vbs_string(title)))
    vbs_path = _data_dir() / "toast_tmp.vbs"
    reason = "not attempted"
    try:
        vbs_path.write_text(vbs, encoding="utf-8")
        proc = subprocess.run(
            ["wscript", "//B", "//Nologo", str(vbs_path)],
            capture_output=True, timeout=TOAST_TIMEOUT_SECONDS + 30)
        if proc.returncode == 0:
            return True, ("WScript.Shell.Popup (auto-dismiss %ds)"
                           % TOAST_TIMEOUT_SECONDS)
        reason = "wscript exited %d" % proc.returncode
    except Exception as exc:
        reason = "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            vbs_path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
        return True, ("MessageBoxW fallback (BLOCKING, click to dismiss) — "
                      "wscript failed: " + reason)
    except Exception as exc:
        return False, ("toast failed — wscript: %s; MessageBoxW: %s: %s"
                       % (reason, type(exc).__name__, exc))


def show(title: str, message: str) -> dict:
    shown = False
    method = "log-only"
    if sys.platform == "win32":
        shown, method = _show_toast_windows(title, message)
    entry = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "title": title, "message": message,
             "shown": shown, "method": method}
    log = _data_dir() / "reminders.log"
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"status": "ok", **entry, "log": str(log)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GENESIS reminder")
    ap.add_argument("--title", default="GENESIS")
    ap.add_argument("--message", required=True)
    args = ap.parse_args(argv)
    print(json.dumps(show(args.title, args.message), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
