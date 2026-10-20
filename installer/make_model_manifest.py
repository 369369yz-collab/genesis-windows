"""Generate the model manifest for first-boot download (Windows CI).

After the model is split into parts and uploaded as release assets,
this writes genesis_onecode/brain/model_manifest.json:
  { "release_tag": ..., "parts": [{"name","size","sha256","url"}, ...],
    "assembled_sha256": ..., "assembled_size": ... }

The Rust launcher reads this manifest from its resources, downloads
missing parts with per-part hash checks, assembles, and verifies the
full pinned SHA-256 (W14). The manifest is committed to the repo —
small, reviewable, versioned.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "app" / "src-tauri" / "resources" / "models"
MANIFEST = REPO_ROOT / "genesis_onecode" / "brain" / "model_manifest.json"
PINS_PATH = REPO_ROOT / "genesis_onecode" / "brain" / "pins.json"

# Model identity comes from pins.json (single source of truth) — never
# hardcoded here, so a model refresh cannot silently revert the manifest.
_PINS = json.loads(PINS_PATH.read_text())
MODEL_NAME = _PINS["local_llm"]["name"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    release_tag = os.environ.get(
        "MODEL_RELEASE_TAG", _PINS["local_llm"].get("release_tag", ""))
    repo = os.environ.get(
        "MODEL_RELEASE_REPO",
        _PINS["local_llm"].get("release_repo", "369369yz-collab/genesis-windows"))
    if not release_tag:
        print("FATAL: no release tag (MODEL_RELEASE_TAG unset and pins.json "
              "local_llm.release_tag missing)", file=sys.stderr)
        return 1
    parts = sorted(MODELS_DIR.glob(MODEL_NAME + ".part*"))
    if not parts:
        print(f"FATAL: no model parts in {MODELS_DIR}", file=sys.stderr)
        return 1
    assembled_sha = _PINS["local_llm"]["sha256"]
    assembled_size = _PINS["local_llm"]["size_bytes"]
    manifest = {
        "release_tag": release_tag,
        "assembled_name": MODEL_NAME,
        "assembled_size": assembled_size,
        "assembled_sha256": assembled_sha,
        "parts": [],
    }
    for part in parts:
        manifest["parts"].append({
            "name": part.name,
            "size": part.stat().st_size,
            "sha256": sha256_file(part),
            "url": (f"https://github.com/{repo}/releases/download/"
                    f"{release_tag}/{part.name}"),
        })
    total = sum(p["size"] for p in manifest["parts"])
    if total != assembled_size:
        print(f"FATAL: parts sum {total} != model size {assembled_size}", file=sys.stderr)
        return 1
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest written: {MANIFEST} ({len(manifest['parts'])} parts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
