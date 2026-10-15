# FIRST-BOOT LARGE-ASSET DOWNLOAD — PRIOR-ART DISSECTION
Mission: REVERSE-ENGINEERING-BEFORE-BUILD (YZ law 2026-10-15).
Target crash: 0xC00000FD (STATUS_STACK_OVERFLOW) ~69s after launch, during first-boot 5GB model download.
Date: 2026-10-15. Analyst: subagent (read-only, zero-spend).

---

## 1. OLLAMA — server/download.go (github.com/ollama/ollama, cloned shallow 2026-10-15)

**Where the code lives:** `server/download.go` — `blobDownload` struct, `Prepare()`, `run()`, `downloadChunk()`, `Wait()`; part state in `blobDownloadPart` (`Name()`, `StartsAt()`, `StopsAt()`, `Write()`).

**What it does (pattern summary, my own words):**
- Downloads run **inside the server process but on Go goroutines**, not OS threads. Go stacks start tiny (~8KB) and *grow dynamically* — the fixed-stack-overflow crash class that killed us **cannot happen** in this design. Concurrency is bounded by an errgroup semaphore (`g.SetLimit(numDownloadParts)`), not by spawning unbounded threads.
- **Resume is structural:** one sparse `-partial` file, pre-truncated to the full size up front; up to 16 parts (clamped 100MB–1000MB each) written concurrently via offset writers into that single file. Each part's progress (`Completed` bytes) is persisted as a small JSON sidecar file (`<blob>-partial-<i>`). On restart, finished parts are skipped; unfinished parts resume with HTTP `Range: bytes=start-stop` requests. No re-download, no separate assembly phase (no 2x disk).
- **Integrity is content-addressed:** the blob's final path *is* its `sha256-<hex>` digest, and `verifyBlob()` re-hashes after completion (see `server/images.go` ~L1262: "verifying sha256 digest"). The hash is a *separate cheap pass*, never a giant in-memory operation.
- **Stall watchdog per chunk:** a second goroutine per download watches `lastUpdated`; if no bytes move for 30s (`downloadStallTimeout`), the chunk is aborted and retried *without consuming the retry budget* (`try--`). Transient network stalls never kill the pull.
- **Backoff with jitter:** registry negotiation uses n² backoff randomized 0.5–1.5x, capped — no thundering herd.
- **Progress IPC:** `Wait(ctx, fn)` — callers pass a callback receiving `ProgressResponse{Status, Digest, Total, Completed}` on a 60ms ticker, fed by atomic counters. The CLI/API layer renders bars from this; the downloader never touches UI code.
- **Deduplication:** `blobDownloadManager.LoadOrStore(digest, ...)` — two pulls of the same blob share one download; refcounted `acquire()/release()` cancels when the last waiter leaves.

**Why it avoids our crash class:** (a) growable stacks — no fixed 2MB thread stack to blow; (b) streaming copies use small internal buffers (io.CopyN ≈ 32KB, heap); (c) hashing is incremental over the stream, never "allocate N megabytes, then read"; (d) the download can stall/retry forever without endangering the server process.

**Pattern to steal:** offset-writer into one pre-sized file + JSON part-state + Range resume + stall watchdog + atomic progress callback. And: hash *while streaming*, not in a second pass.

---

## 2. TAURI PRODUCTION APPS — first-run model download patterns

Surveyed via web/GitHub (readmes + docs, 2026-10-15):

- **omnivoice-studio (Tauri v2, debpalash/voicestudio):** ~5GB first-run model download — *almost exactly our size class*. Architecture: Tauri v2 Rust shell does **only** window/process lifecycle. The download runs in the **Python sidecar/backend** (`backend/utils/hf_progress.py`), which monkey-patches tqdm so every `hf_hub_download()` reports progress; callbacks stream to a `/setup/download/stream` SSE endpoint; the React SetupWizard renders bars and locks the UI until models are ready. **The Rust shell never downloads bytes itself.**
- **saucebunny (Tauri, gchiaramonte3):** heavy ML work (diarizer) is a **separate sidecar binary** (`src-tauri/binaries/<name>-<triple>`); first runtime invocation downloads Core ML models to cache. Progress IPC = **newline-delimited JSON on the sidecar's stdout** (`{"phase":"prepare",...}` → `{"phase":"done",...}`), parsed by the Rust shell into a progress channel. Crash of the sidecar ≠ crash of the app.
- **xtalk (Tauri, xcc-zach):** "On first use, the shell downloads the locked Silero VAD model into the application data directory and verifies its size and SHA-256. Later launches reuse the cached file." Small-model case, but note the order: **size check first (cheap), hash second, cache forever**.
- **local-whisper-win (Tauri, sejeonglee):** first launch downloads Whisper model to `%LOCALAPPDATA%`; later launches reuse. Same cache-forever shape.

**Consensus pattern across all four:** the Rust shell supervises; bytes move in a sidecar/backend process (or at minimum outside the UI thread); progress crosses the boundary as events (SSE / stdout-NDJSON / callbacks); completed assets are cached in the platform app-data dir and never re-fetched. **None of them hash multi-GB files with stack buffers in the main process.**

---

## 3. GENERAL ROBUST-LAUNCHER PATTERNS (crash isolation + stack discipline)

- **Worker-process isolation (strongest):** Chrome's utility-process model, VS Code's extension host, Ollama's `ollama run` vs `ollama serve` split — crash-prone work (network, parsing, ML) lives in a child process; the parent supervises via pipes/exit codes and *cannot* be taken down by a fault in the child. A stack overflow in a child = child dies, parent logs + restarts it.
- **Thread-stack discipline (Rust/Windows specifics):** `std::thread::spawn` gives a **fixed 2 MiB stack on every platform** (documented default of `std::thread::Builder`). There is no growable-stack escape hatch in Rust. Rule: **never put more than ~tens of KB on a thread stack** — large buffers go on the heap (`vec!`, `Box<[u8]>`). `std::thread::Builder::stack_size()` can raise a thread's stack, but that treats the symptom; heap allocation treats the cause.
- **Stream, don't stage:** hash and copy in one pass over a small reused buffer (8–64KB). A second full read pass just to hash doubles disk IO and doubles the window for faults.
- **Fail-closed resume:** partial files + Range requests + per-part state (Ollama) beats our current "delete whole part and retry next boot" — a 512MB part that fails at 511MB currently restarts from zero *next boot*.

---

## 4. OUR ROOT CAUSE — FOUND BY READING OUR OWN CODE

`app/src-tauri/src/brain.rs:119`, function `sha256_file`:

> an 8 MiB byte array allocated as a **stack local** (`let mut buf = [0u8; 8 * 1024 * 1024]`)

The boot thread is created by `std::thread::spawn` (`main.rs:102`) → **2 MiB fixed stack**. The first call to `sha256_file` tries to reserve 8 MiB of stack → guard page → **`0xC00000FD`, guaranteed, every time, on every platform**.

**Why it matches the crash log exactly:** `download_part` streams part 1 (512MB) to disk fine, then calls `sha256_file` to verify the hash — the overflow fires at the *start of hash verification*, i.e. right after "536870912 bytes received", ~69s in. The network code is innocent; the hasher is the bomb.

**Why 7 runs passed first:** the bug is 100% deterministic, but its *trigger* is timing-dependent — `sha256_file` only runs after a part fully downloads. In the 7 passing runs the part never finished inside B1's observation window (slower effective throughput), so the bomb never detonated. In the 6 failing runs the download was fast enough to reach verification. Deterministic bug, probabilistic trigger — the most misleading kind.

**Sweep result:** this is the *only* oversized stack array in the whole Rust codebase (grep for `[0u8; N]` across all of `src/` — one hit). No recursion, no other suspect.

---

## 5. REDESIGN SPEC — brain.rs boot path

### 5.1 The one-line kill (do immediately)
Replace the stack array with a heap buffer:
- `let mut buf = [0u8; 8 * 1024 * 1024];` → `let mut buf = vec![0u8; 8 * 1024 * 1024];` (or shrink to 64KB — 8MB buys nothing for hashing throughput).
- Add a CI gate (grep in the build workflow): fail the build if any `[0u8; <N>]` stack array with N > 65536 appears in `src/`. One line of PowerShell; this bug class can never re-enter.

### 5.2 Architectural redesign (what the prior art demands)
1. **Hash while streaming (steal from Ollama):** wrap the download reader so bytes feed `Sha256` *as they are written to disk* — one pass, no second 512MB re-read, no separate `sha256_file` at all. Compare the running digest against the manifest pin at end-of-stream.
2. **Resume (steal from Ollama's `-partial` + Range):** keep per-part state (bytes completed) in a small JSON sidecar; on boot, issue `Range` requests from the recorded offset instead of deleting and restarting whole 512MB parts. A part interrupted at 511MB resumes at 511MB.
3. **Single pre-sized file (steal from Ollama):** write parts at offsets into one pre-allocated model file instead of 10 part files + a concatenation pass. Deletes the assembly phase (and its 2x transient disk use).
4. **Progress IPC (steal from Ollama `Wait(fn)` + saucebunny NDJSON):** atomic `completed_bytes` counter; emit Tauri events (`genesis://model-progress {part, done, total}`) on a ~250ms ticker for the frontend progress UI. The downloader never touches UI code.
5. **Stall watchdog (steal from Ollama):** if no bytes arrive for 60s, abort the HTTP stream and retry with backoff+jitter (2^n, capped, randomized) — a hung connection must not hang first boot forever.
6. **Isolation hardening (steal from omnivoice/saucebunny sidecar pattern):** move the downloader out of the app process into a tiny dedicated sidecar (`genesis-fetch`), supervised by the Rust shell via stdout-NDJSON progress lines. Then even a future fault in download code kills only the fetcher, never the app. (Phase 2 — the heap-buffer fix + streaming hash unblocks testing now; sidecar extraction follows before final.)
7. **Stack-discipline law (new permanent rule):** no stack allocation > 64KB on any thread, ever; heap for everything bigger; the CI grep gate enforces it.

### What would have prevented this exact 0xC00000FD
Any *one* of: heap buffer instead of stack array (5.1); hashing during the stream (5.2.1 — `sha256_file` wouldn't exist); the CI grep gate (5.1 — the line would never have merged). The deeper lesson from the dissection: **production systems never let byte-moving code share fate with the app process** — isolate the downloader, stream with small buffers, verify incrementally, resume structurally.
