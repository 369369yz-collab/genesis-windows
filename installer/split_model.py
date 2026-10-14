"""Split the model into NSIS-safe parts (Windows CI).

makensis (32-bit) cannot mmap a single 5GB file, so the model ships as
512MB parts inside the installer resources. The Rust brain launcher
reassembles them at boot and re-verifies the pinned SHA-256 (W14) —
the model is byte-identical, just transported in parts.

Idempotent: skips work when parts already exist and are complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "app" / "src-tauri" / "resources" / "models"
MODEL_NAME = "Qwen3-8B-Q4_K_M.gguf"
PART_SIZE = 512 * 1024 * 1024  # 512 MB — safely under makensis mmap limits


def main() -> int:
    model = MODELS_DIR / MODEL_NAME
    if not model.exists():
        # Already split in a previous run (or fresh checkout without fetch).
        parts = sorted(MODELS_DIR.glob(MODEL_NAME + ".part*"))
        if parts:
            print(f"model already split: {len(parts)} parts")
            return 0
        print(f"FATAL: model not found: {model}", file=sys.stderr)
        return 1
    size = model.stat().st_size
    n_parts = (size + PART_SIZE - 1) // PART_SIZE
    print(f"splitting {model.name} ({size} bytes) into {n_parts} x 512MB parts", flush=True)
    with open(model, "rb") as f:
        for i in range(n_parts):
            part = MODELS_DIR / f"{MODEL_NAME}.part{i:02d}"
            with open(part, "wb") as out:
                remaining = PART_SIZE
                while remaining > 0:
                    chunk = f.read(min(8 * 1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            print(f"  wrote {part.name} ({part.stat().st_size} bytes)", flush=True)
    # Verify the split round-trips byte-identically before deleting the whole:
    # hash the concatenated parts and compare against the pinned SHA-256.
    import hashlib, json
    pins = json.loads((REPO_ROOT / "genesis_onecode" / "brain" / "pins.json").read_text())
    expected = pins["local_llm"]["sha256"]
    h = hashlib.sha256()
    for part in sorted(MODELS_DIR.glob(MODEL_NAME + ".part*")):
        with open(part, "rb") as pf:
            for chunk in iter(lambda: pf.read(8 * 1024 * 1024), b""):
                h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        print(f"FATAL: reassembled parts hash mismatch\nexpected {expected}\nactual   {actual}",
              file=sys.stderr)
        return 1
    print(f"split verified: reassembled SHA-256 matches pin")
    model.unlink()
    print(f"split OK: {n_parts} parts, whole file removed (NSIS-safe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
