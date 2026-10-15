#!/usr/bin/env bash
# GENESIS pre-flight gate — YZ LAW 2026-10-15:
# "Nothing consumes GitHub Actions minutes until ALL local gates pass."
# No more burning free minutes on broken builds (E0599-class errors,
# dead UI, untested code). Run this BEFORE every push that could
# trigger a workflow. Exits non-zero on the FIRST failing gate.
#
# Gates (in order):
#   1. cargo check  — Tauri/Rust backend type-check (catches E0599 etc.)
#                    Runs on a scratch copy with CI-equivalent stubs
#                    (generated icons, resource stubs); repo stays pristine.
#   2. npm run build — frontend production build
#   3. pytest        — genesis_onecode Python test suite
#   4. YAML parse    — all .github/workflows/*.yml must parse
#   5. stack arrays  — no MiB-scale Rust stack arrays (0xC00000FD class)
#
# Requirements: rustup stable at ~/.cargo, node/npm, ~/workspace/.venv.
# Tauri's Linux system deps (for gate 1) need:
#   sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.cargo/bin:$PATH"
LOG="/tmp/preflight_gate.log"
SCRATCH="$HOME/workspace/.preflight-scratch"
# Stable cargo target dir: dependency artifacts persist between runs,
# so repeat gate-1 runs take seconds instead of minutes.
PF_TARGET="$HOME/workspace/.pf-target"

run_gate() {
  local name="$1"; shift
  echo "=== GATE: $name ==="
  if "$@" >"$LOG" 2>&1; then
    echo "PASS: $name"
    return 0
  fi
  echo "FAIL: $name"
  echo "--- first 20 lines of output ---"
  head -20 "$LOG"
  if grep -q "gdk-3.0.*not found\|Package .* was not found" "$LOG" 2>/dev/null; then
    echo "--- HINT: Tauri Linux system libs missing. Run:"
    echo "  sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf"
  fi
  return 1
}

# Gate 1: cargo check on a scratch copy (repo stays pristine).
# CI generates icons/ (installer/make_icons.py) and fetches resources/
# at build time; neither is vendored, so we stub both in scratch only.
gate1_cargo() {
  rm -rf "$SCRATCH"
  mkdir -p "$SCRATCH"
  cp -r "$REPO/app" "$SCRATCH/app"
  rm -rf "$SCRATCH/app/node_modules" "$SCRATCH/app/src-tauri/target"
  local st="$SCRATCH/app/src-tauri"
  # 1a. icons (same PNGs CI generates via installer/make_icons.py)
  python3 - "$REPO/installer/make_icons.py" "$st/icons" <<'EOF'
import ast, base64, pathlib, sys
icons = None
for node in ast.walk(ast.parse(pathlib.Path(sys.argv[1]).read_text())):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'ICONS':
        icons = ast.literal_eval(node.value)
d = pathlib.Path(sys.argv[2]); d.mkdir(parents=True, exist_ok=True)
for name, b64 in icons.items():
    (d / name).write_bytes(base64.b64decode(b64))
print('icons:', len(icons))
EOF
  # 1b. resource stubs (real binaries are fetched by CI; existence is all
  #     tauri_build's build.rs validates)
  mkdir -p "$st/resources/python" "$st/resources/brain" "$st/resources/chromium"
  touch "$st/resources/llama-server.exe"
  # 1c. type-check (PF_TARGET persists between runs for speed)
  ( cd "$st" && CARGO_TARGET_DIR="$PF_TARGET" cargo check --message-format short )
  local rc=$?
  rm -rf "$SCRATCH"
  return $rc
}

run_gate "1/5 cargo check (Tauri backend)" gate1_cargo || exit 1

run_gate "2/5 npm run build (frontend)" \
  bash -c "cd '$REPO/app' && npm run build" || exit 1

run_gate "3/5 pytest (genesis_onecode)" \
  "$HOME/workspace/.venv/bin/python" -m pytest "$REPO/genesis_onecode" -x -q || exit 1

run_gate "4/5 workflows YAML parse" \
  python3 -c "
import yaml, glob
files = sorted(glob.glob('$REPO/.github/workflows/*.yml'))
assert files, 'no workflow files found'
for f in files:
    yaml.safe_load(open(f))
print('parsed', len(files), 'workflows')
" || exit 1

# Gate 5: stack-discipline — no MiB-scale stack arrays in Rust (2026-10-15:
# an 8 MiB stack array on a 2 MiB thread stack = 0xC00000FD crash).
# Heap (vec![...]) is fine; bare let buf = [...; N * 1024 * 1024] is banned.
run_gate "5/5 no large stack arrays (Rust)" \
  python3 -c "
import re, pathlib
src = pathlib.Path('$REPO/app/src-tauri/src')
bad = []
for f in src.rglob('*.rs'):
    for i, line in enumerate(f.read_text().splitlines(), 1):
        for m in re.finditer(r'\[\s*\w+\s*;\s*[0-9][0-9_ ]*(?:\* *[0-9][0-9_ ]*)*\s*\]', line):
            expr = m.group(0)
            if '1024' in expr and not line[:m.start()].rstrip().endswith('vec!'):
                bad.append(f'{f.name}:{i}: {line.strip()}')
if bad:
    print('\n'.join(bad)); raise SystemExit(1)
print('no MiB-scale stack arrays')
" || exit 1

echo ""
echo "ALL PRE-FLIGHT GATES PASSED — safe to push."
