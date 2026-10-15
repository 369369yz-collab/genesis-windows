"""Fetch the local LLM + llama-server for GENESIS Full (Windows CI).

Pins come from genesis_onecode/brain/pins.json (single source of truth):
- Qwen3-8B-Q4_K_M.gguf @ pinned HF commit, SHA-256 verified after download.
- llama.cpp release b11583 (Windows Vulkan build) -> llama-server.exe.

Any hash mismatch => hard failure. Nothing unverified ships.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((REPO_ROOT / "genesis_onecode" / "brain" / "pins.json").read_text())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"downloading {url} -> {dest} ({dest.stat().st_size if dest.exists() else 0} bytes cached)", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "GENESIS-Full-Installer/1.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(8 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def fetch_model(out_dir: Path) -> Path:
    pin = PINS["local_llm"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / pin["name"]
    url = (f"https://huggingface.co/{pin['hf_repo']}/resolve/"
           f"{pin['hf_commit']}/{pin['name']}")
    if not dest.exists():
        download(url, dest)
    actual = sha256_file(dest)
    if actual != pin["sha256"]:
        dest.unlink(missing_ok=True)
        raise SystemExit(
            f"FATAL: model SHA-256 mismatch.\nexpected {pin['sha256']}\nactual   {actual}")
    print(f"model OK: {dest} ({dest.stat().st_size} bytes, sha256 verified)")
    return dest


def fetch_llama_server(out_dir: Path) -> Path:
    # Dual sidecar (HUMANFLOW-RED 2026-10-15, run 38769194892): the Vulkan
    # build cannot run where the Vulkan loader is absent (GitHub runners:
    # no GPU, no vulkan-1.dll — it hung 600s twice with empty stderr and
    # /health never 200). The app picks the right build at boot and falls
    # back to the other one, so both must ship.
    pin = PINS["llama_cpp"]
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = pin["tag"]
    builds = [
        # Vulkan build: GPU acceleration on any modern NVIDIA/AMD/Intel GPU
        # (incl. RTX 50-series Blackwell, where versioned CUDA builds lag).
        ("vulkan", f"llama-{tag}-bin-win-vulkan-x64.zip"),
        # CPU build: runs everywhere, incl. GPU-less CI runners / VMs.
        ("cpu", f"llama-{tag}-bin-win-cpu-x64.zip"),
    ]
    first = None
    for flavor, zipname in builds:
        dest = out_dir / f"llama-server-{flavor}.exe"
        if dest.exists():
            print(f"llama-server-{flavor} cached: {dest}")
        else:
            url = (f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/"
                   f"{zipname}")
            zpath = out_dir / f"llama-{flavor}.zip"
            download(url, zpath)
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    if name.lower().endswith("llama-server.exe"):
                        dest.write_bytes(z.read(name))
                        break
            zpath.unlink(missing_ok=True)
            if not dest.exists():
                raise SystemExit(f"FATAL: llama-server.exe not found in {zipname}")
            print(f"llama-server-{flavor} OK: {dest} ({dest.stat().st_size} bytes)")
        if first is None:
            first = dest
    return first


def main() -> int:
    import os
    # Payloads ship INSIDE the installer as Tauri resources.
    sidecars = REPO_ROOT / "app" / "src-tauri" / "resources"
    # The 5GB model is NOT bundled (NSIS/makensis 32-bit cannot build it).
    # It ships as release parts; the app downloads + verifies on first boot.
    if os.environ.get("GENESIS_SKIP_MODEL", "") != "1":
        fetch_model(sidecars / "models")
    fetch_llama_server(sidecars)
    print("ALL SIDEEARS READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
