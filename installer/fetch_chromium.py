"""Fetch the portable Chromium for GENESIS Full (Windows CI).

Strategy (pinned, zero-spend): install the pinned Playwright and let it
download its matching Chromium build. Prints the chrome.exe path for the
sidecar. Fails loudly on any error — never a silent fake.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PLAYWRIGHT_PIN = "1.49.1"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    run([sys.executable, "-m", "pip", "install", f"playwright=={PLAYWRIGHT_PIN}"])
    run([sys.executable, "-m", "playwright", "install", "chromium"])
    # Resolve the executable path via playwright's own registry.
    code = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    print(p.chromium.executable_path)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], check=True,
                         capture_output=True, text=True)
    exe = out.stdout.strip().splitlines()[-1]
    exe_path = Path(exe)
    if not exe_path.exists():
        print(f"FATAL: chromium executable not found at {exe}", file=sys.stderr)
        return 1
    print(f"CHROMIUM_EXE={exe}")
    Path("chromium_path.txt").write_text(exe, encoding="utf-8")
    # Stage a portable copy INSIDE the installer resources.
    # exe = .../chromium-XXXX/chrome-win/chrome.exe ; copy the chrome-win dir.
    repo_root = Path(__file__).resolve().parents[1]
    dest = repo_root / "app" / "src-tauri" / "resources" / "chromium"
    chrome_win = exe_path.parent  # the chrome-win directory
    if not (dest / "chrome.exe").exists():
        print(f"staging portable chromium -> {dest}", flush=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(chrome_win, dest, ignore=shutil.ignore_patterns("*.pdb"))
        got = dest / "chrome.exe"
        if not got.exists():
            print(f"FATAL: chrome.exe missing after staging: {got}")
            return 1
        print(f"portable chromium staged ({sum(f.stat().st_size for f in dest.rglob('*') if f.is_file())} bytes)")
    else:
        print(f"portable chromium cached: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
