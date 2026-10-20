"""Fetch the local LLM + llama-server for GENESIS Full (Windows CI).

Pins come from genesis_onecode/brain/pins.json (single source of truth):
- The pinned local LLM (see pins.json local_llm.name), SHA-256 verified
  after download. NOTE: the current pin (GENESIS 369 v1, brain-model-v2)
  is our own fine-tune and is NOT published on Hugging Face — it ships as
  verified parts on this repo's GitHub release and the app downloads it on
  first boot via brain/model_manifest.json. fetch_model() therefore only
  downloads a model when the pin carries an hf_repo/hf_commit source, and
  fails closed with an explanation otherwise.
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
    if not (pin.get("hf_repo") and pin.get("hf_commit")):
        raise SystemExit(
            "FATAL: pinned model %s has no Hugging Face source in pins.json. "
            "It is distributed as verified parts on the %s GitHub release "
            "(%s) and downloaded by the app on first boot — there is no "
            "whole-file CI fetch for it." % (
                pin["name"], pin.get("release_tag", "?"),
                pin.get("release_repo", "?")))
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
    #
    # CRITICAL (follow-up, same RED): llama-server.exe is a 9KB STUB that
    # imports llama-server-impl.dll plus the ggml/llama DLL closure
    # (verified via PE import table: llama-server-impl.dll -> llama.dll,
    # llama-common.dll, ggml.dll, ggml-base.dll -> libomp.dll, mtmd.dll).
    # Shipping ONLY the exe meant the installed binary died in the Windows
    # loader on EVERY machine (no stderr, /health never up) — including
    # YZ's PC. Every *.dll from the zips must ship NEXT TO the exes
    # (the loader's first search dir is the exe's own directory).
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
    # Import-closure DLLs the stub exe cannot start without (from objdump of
    # the b11583 binaries). Fail-closed below if any is missing.
    required_dlls = {
        "llama-server-impl.dll",
        "llama.dll",
        "llama-common.dll",
        "ggml.dll",
        "ggml-base.dll",
        "libomp.dll",
        "mtmd.dll",
    }
    first = None
    for flavor, zipname in builds:
        dest = out_dir / f"llama-server-{flavor}.exe"
        if dest.exists() and all((out_dir / d).exists() for d in required_dlls):
            print(f"llama-server-{flavor} cached: {dest}")
        else:
            url = (f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/"
                   f"{zipname}")
            zpath = out_dir / f"llama-{flavor}.zip"
            download(url, zpath)
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    low = name.lower()
                    leaf = Path(name).name
                    if low.endswith("llama-server.exe"):
                        dest.write_bytes(z.read(name))
                    elif low.endswith(".dll"):
                        # Both builds are the same tag/commit, so their
                        # common DLLs are identical; keep the first copy
                        # (vulkan zip is extracted first and is the superset —
                        # it additionally carries ggml-vulkan.dll).
                        target = out_dir / leaf
                        if not target.exists():
                            target.write_bytes(z.read(name))
            zpath.unlink(missing_ok=True)
            if not dest.exists():
                raise SystemExit(f"FATAL: llama-server.exe not found in {zipname}")
            print(f"llama-server-{flavor} OK: {dest} ({dest.stat().st_size} bytes)")
        if first is None:
            first = dest
    # Fail-closed: the exe alone is a dead binary. Every closure DLL plus at
    # least one ggml-cpu-* backend must be staged, or the build stops here.
    problems = [
        d for d in sorted(required_dlls) if not (out_dir / d).exists()
    ]
    if not any(p.name.startswith("ggml-cpu-") for p in out_dir.glob("*.dll")):
        problems.append("ggml-cpu-*.dll (no CPU backend DLL staged)")
    if problems:
        raise SystemExit(
            "FATAL: llama.cpp sidecar DLL closure incomplete — "
            "llama-server.exe cannot start without these: " + ", ".join(problems)
        )
    ndll = len(list(out_dir.glob("*.dll")))
    print(f"llama-server sidecar COMPLETE: 2 exes + {ndll} DLLs in {out_dir}")
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
