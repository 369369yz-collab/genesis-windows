#!/usr/bin/env bash
# GENESIS Final — FULL setup assembly (build VM, Linux).
#
# Produces ONE self-contained setup .exe (~6.1 GB):
#   7z SFX stub (Windows GUI, from the official 7-Zip distribution)
#   + sfx_config.txt
#   + a stored (uncompressed) 7z archive containing:
#       setup/GENESIS-Full-Setup.exe   the green-CI Tauri/NSIS installer
#       payload/genesis_369_v1_Q5_K_M.gguf   the assembled brain model
#       full-launcher.exe              native bootstrap (full-launcher.c)
#
# Why not NSIS alone: makensis is 32-bit and cannot build a >4 GB package
# (app/src-tauri/src/brain.rs header + installer/fetch_model.py document
# this). The 7z format has 64-bit offsets; the SFX stub is standard vendor
# code from 7-zip.org. The app binary itself ALWAYS comes from the green
# GitHub Actions Windows build — never from this VM.
#
# Usage:
#   SETUP_EXE=/path/to/GENESIS-Final-setup.exe \
#   MODEL=/path/to/genesis_369_v1_Q5_K_M.gguf \
#   OUT=/path/to/GENESIS-Final-FULL-Setup.exe \
#   bash installer/full/build_full_setup.sh
#
# Tools (persistent, under ~/workspace/genesis_full_setup/tools):
#   7zz (official 7-Zip Linux binary), winpkg/7z.sfx (Windows GUI SFX
#   module from the official 7z2301-x64.exe), zig (launcher cross-build).
set -euo pipefail

MODEL_SHA_PIN="1a762d6d2c9cd7c34d2497dad1cbb67b4f77f43dccb8cd1efe7f925b9a7e4371"
MODEL_SIZE=5851112800
TOOLS="${TOOLS:-$HOME/workspace/genesis_full_setup/tools}"
SEVEN_ZZ="${SEVEN_ZZ:-$TOOLS/7zz}"
SFX_STUB="${SFX_STUB:-$TOOLS/winpkg/7z.sfx}"
ZIG="${ZIG:-$TOOLS/zig-linux-x86_64-0.13.0/zig}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${SETUP_EXE:?set SETUP_EXE to the green-CI NSIS installer}"
: "${MODEL:?set MODEL to the assembled GGUF}"
: "${OUT:?set OUT to the final setup .exe path}"

echo "== verify inputs =="
[ -f "$SETUP_EXE" ] || { echo "FATAL: SETUP_EXE not found: $SETUP_EXE"; exit 1; }
[ -f "$MODEL" ] || { echo "FATAL: MODEL not found: $MODEL"; exit 1; }
SZ="$(stat -c%s "$MODEL")"
[ "$SZ" = "$MODEL_SIZE" ] || { echo "FATAL: model size $SZ != $MODEL_SIZE"; exit 1; }
HS="$(sha256sum "$MODEL" | cut -d' ' -f1)"
[ "$HS" = "$MODEL_SHA_PIN" ] || { echo "FATAL: model sha256 $HS != pin"; exit 1; }
SETUP_SHA="$(sha256sum "$SETUP_EXE" | cut -d' ' -f1)"
SETUP_SIZE="$(stat -c%s "$SETUP_EXE")"
echo "model OK ($SZ bytes, sha256 verified)"
echo "setup OK ($SETUP_SIZE bytes, sha256 $SETUP_SHA)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/genesis_full.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/payload" "$WORK/setup"

echo "== build launcher =="
"$ZIG" cc -target x86_64-windows-gnu -O2 -s \
    -o "$WORK/full-launcher.exe" "$HERE/full-launcher.c" -lbcrypt

echo "== stage payload =="
cp "$SETUP_EXE" "$WORK/setup/GENESIS-Full-Setup.exe"
cp "$MODEL" "$WORK/payload/genesis_369_v1_Q5_K_M.gguf"

echo "== pack archive (store mode: payloads are already dense) =="
( cd "$WORK" && "$SEVEN_ZZ" a -t7z -mx=0 -mmt=on "$WORK/payload.7z" \
    setup payload full-launcher.exe >/dev/null )

echo "== assemble SFX =="
mkdir -p "$(dirname "$OUT")"
cat "$SFX_STUB" "$HERE/sfx_config.txt" "$WORK/payload.7z" > "$OUT"

OUT_SIZE="$(stat -c%s "$OUT")"
OUT_SHA="$(sha256sum "$OUT" | cut -d' ' -f1)"
echo "FULL SETUP BUILT: $OUT"
echo "  size:   $OUT_SIZE bytes"
echo "  sha256: $OUT_SHA"
echo "  contains: setup ($SETUP_SIZE B, sha256 $SETUP_SHA) + model ($SZ B, pin-verified) + launcher"
