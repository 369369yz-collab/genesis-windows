# GENESIS Final — FULL setup (one file, everything inside, zero downloads)

YZ order 2026-10-21 ~16:22 Tehran: the final setup must be complete —
«بدون هیچ کم و کسری» — install it and everything is ready, no first-boot
downloads, no other work. genesis-final-0.1.0 broke that promise: its
first boot silently downloaded the 5.85 GB brain model with no visible
progress (and a cut connection looked like a freeze). This directory is
the fix.

## First-boot download inventory (genesis-final-0.1.0, build 39523679215)

Every network fetch the shipped app can make before it is fully ready:

| # | What | Where | When | In FULL setup |
|---|------|-------|------|----------------|
| 1 | Brain model, 11 parts, 5,851,112,800 B total | `app/src-tauri/src/brain.rs` `download_part()` / `ensure_model()`; URLs in `genesis_onecode/brain/model_manifest.json` (GitHub release `brain-model-v2`) | First boot, ONLY if the assembled GGUF is absent from `%LOCALAPPDATA%\com.genesis.final\models\` | **Pre-placed by the launcher before first launch — download never triggers** |
| 2 | Tauri updater check (`latest.json`) | `app/src-tauri/tauri.conf.json` plugins.updater | Background update check; never blocks readiness, downloads nothing unless the user approves an update in Settings | Nothing to bundle (not a payload) |

Everything else is already inside the NSIS installer as Tauri resources,
staged by CI (`build-windows.yml`): llama-server Vulkan+CPU exes and the
full DLL closure (`installer/fetch_model.py`, GENESIS_SKIP_MODEL=1),
portable Python (`installer/fetch_python.py`), portable Chromium
(`installer/fetch_chromium.py`), the brain code (`installer/stage_brain.py`).
All remaining app traffic is localhost (llama 127.0.0.1:8080, brain
127.0.0.1:17369); the cloud bridge client (`genesis_onecode/brain/sync.py`)
is dormant unless configured. The birth test's "llama-server.exe missing"
note (B4) was a probe for a literal filename that never exists by design —
the payloads are `llama-server-vulkan.exe` / `llama-server-cpu.exe`, and
the passing human-flow run proved llama serving from the installed bundle.

## Route

- **Not NSIS**: makensis is 32-bit and cannot build a >4 GB package
  (documented in `app/src-tauri/src/brain.rs` header and
  `installer/fetch_model.py`). Total FULL payload is ~6.03 GB.
- **Not GitHub Actions assembly**: windows-latest disk headroom vs a
  5.85 GB model + 11.7 GB transient (parts + assembled) + build tree is
  too tight, and the model already lives on the build VM. The APP binary
  still comes from the green CI Windows build — only the final wrap is
  assembled locally (`build_full_setup.sh`).
- **Chosen**: one file = official 7-Zip GUI SFX stub (from the official
  7z2301-x64 distribution) + `sfx_config.txt` + a stored 7z archive with
  `setup/` (CI installer), `payload/` (assembled GGUF), and
  `full-launcher.exe` — a dependency-free native Win32 bootstrap
  (`full-launcher.c`, cross-built with Zig) that installs the app,
  places the model with CopyFileEx progress, verifies the W14 SHA-256
  pin with BCrypt, and launches GENESIS. The 7z format uses 64-bit
  offsets, so the >4 GB archive is well inside spec; the archive is
  verified on the build VM by full extraction + SHA-256 of every payload
  before the file ever leaves.

Delivery to the user is a single file via Google Drive (GitHub release
assets cap at 2 GB/file).

## Progress honesty (the other half of the fix)

Even with the model pre-placed, first boot still verifies 5.85 GB —
that state is now VISIBLE in the app:

- `brain.rs`: `sha256_file_cb` reports bytes hashed; `verify_model_progress`
  drives model_state ("verifying", done, total); part downloads stream
  per-byte progress (16 MB steps) instead of jumping per ~512 MB part.
- `app/src/main.js` + `index.html` + `styles.css`: a boot progress bar
  polls the previously-unrendered `brain_status` command and shows the
  state + percent until the brain service is up (errors shown, not hidden).
