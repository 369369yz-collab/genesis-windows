#!/usr/bin/env bash
# GENESIS Complete 1.0.0 — BOOTSTRAPPER build (build VM, Linux, zero spend).
#
# Produces ONE small Windows x64 console executable (~2.6 MB):
#   GENESIS.Complete_1.0.0_x64-bootstrapper.exe
# from bootstrapper.c + the official 7-Zip x64 engine binaries in engine/
# (7z.exe / 7z.dll extracted untouched from the official 7z2605-x64.exe;
# see engine/PROVENANCE.md for sizes + sha256 pins).
#
# Why a bootstrapper: the single-file 6.03 GB SFX setup is byte-verified
# but the Windows loader refuses to launch ANY >4 GiB executable
# (complete-verify runs 39665797415 / 39678558530 / 39764072162, Win32
# error 193 class at the launch step). The bootstrapper is small, joins
# the 4 published parts, sha256-verifies the join against the release
# pin, extracts the payload with the embedded engine, and runs the
# payload's full-launcher.exe. See bootstrapper.c header for the flow.
#
# Usage:  bash installer/bootstrapper/build_bootstrapper.sh [OUT]
# Tools:  zig (persistent, ~/workspace/genesis_full_setup/tools), python3.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="${TOOLS:-$HOME/workspace/genesis_full_setup/tools}"
ZIG="${ZIG:-$TOOLS/zig-linux-x86_64-0.13.0/zig}"
PY="${PY:-$HOME/workspace/.venv/bin/python}"
OUT="${1:-$HERE/GENESIS.Complete_1.0.0_x64-bootstrapper.exe}"

EXPECTED_7Z_EXE_SHA="94205cfc054dd3bbeb978905bc619a65b3f04e9e73bb2717841110b6f46d962e"
EXPECTED_7Z_DLL_SHA="78bf6b668d75801e3aa180b4ccb16e6d8395fba80dec8a065055bb6f8dfabb82"

echo "== verify engine pins =="
for pair in "7z.exe:$EXPECTED_7Z_EXE_SHA" "7z.dll:$EXPECTED_7Z_DLL_SHA"; do
    f="${pair%%:*}"; want="${pair##*:}"
    got="$(sha256sum "$HERE/engine/$f" | cut -d' ' -f1)"
    [ "$got" = "$want" ] || { echo "FATAL: engine/$f sha256 $got != pin $want"; exit 1; }
    echo "engine/$f OK (sha256 = pin)"
done

echo "== generate embedded blobs =="
"$PY" "$HERE/gen_engine_blobs.py" "$HERE/engine/7z.exe" "$HERE/engine/7z.dll" "$HERE/engine_blobs.h"

echo "== compile (zig cc, x86_64-windows-gnu) =="
"$ZIG" cc -target x86_64-windows-gnu -O2 -s -Wall -Wextra \
    -o "$OUT" "$HERE/bootstrapper.c" -lbcrypt

SZ="$(stat -c%s "$OUT")"
HS="$(sha256sum "$OUT" | cut -d' ' -f1)"
echo "BOOTSTRAPPER BUILT: $OUT"
echo "  size:   $SZ bytes"
echo "  sha256: $HS"
