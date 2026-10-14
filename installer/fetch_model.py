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
    pin = PINS["llama_cpp"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "llama-server.exe"
    if dest.exists():
        print(f"llama-server cached: {dest}")
        return dest
    tag = pin["tag"]
    # Vulkan build: GPU acceleration on any modern NVIDIA/AMD/Intel GPU
    # (incl. RTX 50-series Blackwell, where versioned CUDA builds lag).
    url = (f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/"
           f"llama-{tag}-bin-win-vulkan-x64.zip")
    zpath = out_dir / "llama.zip"
    download(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if name.lower().endswith("llama-server.exe"):
                data = z.read(name)
                dest.write_bytes(data)
                break
    zpath.unlink(missing_ok=True)
    if not dest.exists():
        raise SystemExit("FATAL: llama-server.exe not found in llama.cpp release zip")
    print(f"llama-server OK: {dest} ({dest.stat().st_size} bytes)")
    return dest


def main() -> int:
    # Payloads ship INSIDE the installer as Tauri resources.
    sidecars = REPO_ROOT / "app" / "src-tauri" / "resources"
    fetch_model(sidecars / "models")
    fetch_llama_server(sidecars)
    print("ALL SIDEEARS READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
