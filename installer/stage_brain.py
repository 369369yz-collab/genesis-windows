"""Stage the GENESIS brain (one-code) into the installer resources.

Copies genesis_onecode/ -> app/src-tauri/resources/brain/genesis_onecode/
so the installed app carries her brain inside (BRAIN-IS-WORLD law).

Pure stdlib brain: no pip install needed. Fails loudly if the tree is
missing or empty.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "genesis_onecode"
DEST = REPO_ROOT / "app" / "src-tauri" / "resources" / "brain" / "genesis_onecode"


def main() -> int:
    if not SRC.is_dir():
        print(f"FATAL: brain source missing: {SRC}", file=sys.stderr)
        return 1
    py_files = list(SRC.rglob("*.py"))
    if not py_files:
        print(f"FATAL: no python files in {SRC}", file=sys.stderr)
        return 1
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, DEST, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    staged = list(DEST.rglob("*.py"))
    print(f"brain staged: {len(staged)} py files -> {DEST}")
    # The service entrypoint must exist.
    if not (DEST / "service.py").exists():
        print(f"FATAL: genesis_onecode/service.py missing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
