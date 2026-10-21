"""Assemble the pinned brain model from its release parts.

Inverse of split_model.py: reads genesis_onecode/brain/model_manifest.json,
concatenates the parts (downloaded from the brain-model-v2 release) in
manifest order, and verifies size + full SHA-256 against the manifest pin
(W14). Fail-closed: any mismatch deletes the output and exits nonzero.

Usage:
    python installer/assemble_model.py <parts_dir> <out_file>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "genesis_onecode" / "brain" / "model_manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    parts_dir, out_file = Path(sys.argv[1]), Path(sys.argv[2])
    m = json.loads(MANIFEST.read_text())
    out_file.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(out_file, "wb") as out:
        for p in m["parts"]:
            part = parts_dir / p["name"]
            if not part.exists():
                print(f"FATAL: missing part {part}", file=sys.stderr)
                out_file.unlink(missing_ok=True)
                return 1
            if part.stat().st_size != p["size"]:
                print(f"FATAL: part size mismatch {p['name']}", file=sys.stderr)
                out_file.unlink(missing_ok=True)
                return 1
            with open(part, "rb") as f:
                for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                    out.write(chunk)
            total += p["size"]
            print(f"part ok: {p['name']} ({p['size']} B)")
    size = out_file.stat().st_size
    if size != m["assembled_size"] or total != m["assembled_size"]:
        print(f"FATAL: assembled size {size} != pin {m['assembled_size']}", file=sys.stderr)
        out_file.unlink(missing_ok=True)
        return 1
    actual = sha256_file(out_file)
    if actual != m["assembled_sha256"]:
        print(f"FATAL: assembled sha256 {actual} != pin {m['assembled_sha256']}",
              file=sys.stderr)
        out_file.unlink(missing_ok=True)
        return 1
    print(f"model assembled + verified: {out_file} ({size} B, sha256 {actual})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
