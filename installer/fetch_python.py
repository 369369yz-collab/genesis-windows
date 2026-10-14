"""Fetch portable CPython for GENESIS Full (Windows CI).

Downloads astral-sh/python-build-standalone (pinned release, install_only
tarball), verifies the tarball against the release's published SHA256SUMS,
and extracts it to app/src-tauri/resources/python/.

The bundled python.exe runs the brain service on YZ's PC — no system
Python required (standalone law).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "app" / "src-tauri" / "resources" / "python"

RELEASE_TAG = "20261013"
TARBALL = "cpython-3.12.15+20261013-x86_64-pc-windows-msvc-install_only.tar.gz"
BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE_TAG}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"downloading {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "GENESIS-Full-Installer/1.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, length=8 * 1024 * 1024)


def main() -> int:
    if (OUT_DIR / "python.exe").exists():
        print(f"portable python cached: {OUT_DIR}")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    work = REPO_ROOT / "installer" / ".work-python"
    work.mkdir(parents=True, exist_ok=True)
    sums_path = work / "SHA256SUMS"
    tgz_path = work / TARBALL
    if not sums_path.exists():
        download(f"{BASE}/SHA256SUMS", sums_path)
    if not tgz_path.exists():
        download(f"{BASE}/{TARBALL}", tgz_path)
    # Verify against the publisher's own checksum file.
    expected = None
    for line in sums_path.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].endswith(TARBALL):
            expected = parts[0]
            break
    if not expected:
        print(f"FATAL: {TARBALL} not listed in SHA256SUMS", file=sys.stderr)
        return 1
    actual = sha256_file(tgz_path)
    if actual != expected:
        print(f"FATAL: python tarball SHA-256 mismatch\n expected {expected}\n actual   {actual}",
              file=sys.stderr)
        return 1
    print(f"python tarball verified: {actual[:16]}...")
    with tarfile.open(tgz_path, "r:gz") as t:
        t.extractall(work / "extracted")
    # install_only layout: <work>/extracted/python/{python.exe, ...}
    src = work / "extracted" / "python"
    if not (src / "python.exe").exists():
        print(f"FATAL: python.exe not found in {src}", file=sys.stderr)
        return 1
    for item in src.iterdir():
        dest = OUT_DIR / item.name
        if dest.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    exe = OUT_DIR / "python.exe"
    if not exe.exists():
        print("FATAL: python.exe missing after copy", file=sys.stderr)
        return 1
    # Sanity: the bundled interpreter must actually run.
    r = subprocess.run([str(exe), "-c", "import sys; print(sys.version)"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"FATAL: bundled python.exe failed to run:\n{r.stderr}", file=sys.stderr)
        return 1
    print(f"portable python OK: {r.stdout.strip().splitlines()[0]}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
