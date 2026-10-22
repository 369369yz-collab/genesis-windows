# GENESIS Complete 1.0.0 — Bootstrapper

Small native Win32 bootstrapper (`bootstrapper.c`, ~2.6 MB, no runtime
dependencies) that replaces the un-launchable single-file 6.03 GB SFX
setup as the user-facing entry point of GENESIS Complete 1.0.0.

## Why

Three CI runs (39665797415, 39678558530, 39764072162) proved the same
fact three ways: the joined setup bytes are sha256-exact and PE-0x8664,
yet the Windows loader rejects the >4 GiB single file at launch
(Win32 error 193 class) before any code runs. Every GENESIS executable
under 4 GiB launches fine. So the entry point becomes small, and the
verified bytes ship as parts it assembles locally.

## User flow

1. Download all 5 files from the `genesis-complete-1.0.0` prerelease
   into ONE folder: the bootstrapper + `…setup.exe.part-00..03`.
2. Run `GENESIS.Complete_1.0.0_x64-bootstrapper.exe`.
3. It joins the parts → verifies SHA-256 against the release pin
   (fail-closed; a bad join is deleted, nothing installs) → extracts
   the payload with the embedded official 7-Zip x64 engine → runs the
   payload's `full-launcher.exe`, which installs the app, places and
   sha-verifies the 5.85 GB brain model, and launches GENESIS.
   Progress is visible at every phase.

The payload is reused byte-for-byte; nothing is repacked.

## Pins

- Joined file: 6,030,832,317 B, sha256
  `7edb42627afde8163724e2b2b9709d96f83ab09120bc331821b92541f7721f4e`
- Parts: 1,572,864,000 / 1,572,864,000 / 1,572,864,000 / 1,312,240,317 B
- Payload entries: `setup/GENESIS-Full-Setup.exe` 179,629,850 B ·
  `payload/genesis_369_v1_Q5_K_M.gguf` 5,851,112,800 B ·
  `full-launcher.exe` 43,520 B
- Engine: see `engine/PROVENANCE.md`

## Build

`bash build_bootstrapper.sh` — generates `engine_blobs.h` (git-ignored)
from `engine/7z.exe` + `engine/7z.dll` after pin verification, then
cross-compiles with zig cc (`x86_64-windows-gnu`), same toolchain and
pattern as `installer/full/full-launcher.c`.

## CI

`complete-verify.yml` (V3) and `complete-birth.yml` (B2) exercise this
exact flow when `COMPLETE_SETUP_KIND=boot`: the parts and the
bootstrapper asset (pin-checked against `COMPLETE_BOOTSTRAPPER_SHA256`
/ `COMPLETE_BOOTSTRAPPER_SIZE` repo vars) are downloaded into one
folder and the bootstrapper is run, exactly as a user runs it.
