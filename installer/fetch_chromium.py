"""Fetch the portable Chromium for GENESIS Full (Windows CI).

Strategy (pinned, zero-spend): install the pinned Playwright and let it
download its matching Chromium build. Prints the chrome.exe path for the
sidecar. Fails loudly on any error — never a silent fake.
"""
from __future__ import annotations

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
