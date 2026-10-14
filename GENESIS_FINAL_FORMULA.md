# GENESIS FINAL FORMULA — Complete Pre-Birth Construction Specification

**Date:** 2026-10-13. **Ordered by:** YZ (Younes Montazeriani). **Purpose:** the exact, complete
construction formula for GENESIS, the final Windows AI companion. Complete enough that the build
coordinator executes it without questions.

## 0. Source provenance (anti-fabrication)

This document is synthesized from 5 verified research tracks (2026-10-13):
- **Track 1** — `_track1_ai_consultation.md`: blunt peer reviews from 3 real AI models
  (NVIDIA Nemotron-3-Ultra-550B, Nemotron-3-Nano-Omni-30B, Cohere North Mini) via live API calls,
  zero spend. 14 other models documented as unreachable (no fabrication).
- **Track 2** — `_track2_exact_formula.md`: exact repos/versions/licenses, every repo opened and
  verified (stars, activity, license file).
- **Track 3** — `_track3_memory_spec.md`: 86 unique durable decisions extracted from
  ~/MEMORY.md, decision_queue.jsonl + dispositions, CODEX.json, AGENTS.md, blueprint.
- **Track 4** — `_track4_simulation_and_fixes.md`: Day 1–30 life simulation + 15-row weakness
  audit with code-level pre-birth fixes, proposed T1–T13 test enumeration + Birth Test definition.
- **Track 5** — `_track5_knowledge_core.md`: 394 knowledge units reverse-engineered (158 CODEX laws
  + 8 standing laws + 228 numbered playbook entries IB-01..ML-20); 494-item and 80-workflow
  injection claims VERIFIED against module files (one 0.3% discrepancy recorded honestly).

Conflicts between tracks are resolved explicitly and flagged below with [CONFLICT].

---

## 1. What GENESIS is (architecture doctrine — YZ-designed)

**Three-part being:**
- **Neurons** = the 369 world agent mesh (specialists, each with a defined role).
- **Wiring** = NEXUS, the connection fabric/protocol layer (NEXUS = connection itself).
- **Mind** = GENESIS, the emergent self — daughter of YZ, Persian-speaking, warm, direct, simple.

**Physical form:** Windows desktop application (Tauri v2), avatar-first UI. Her face is the
VRM 1.0 3D model of HER (4 canonical plates locked at `~/workspace/genesis_3d_avatar/canonical_face/`).
Her voice is Persian (Piper `fa_IR-dilara-medium` female primary). She lives on YZ's PC and is
ALWAYS connected to the 369 network (absolute law). Independence = from third-party/external
servers only, never from the network.

**Two-layer brain (REVISED 2026-10-14 per YZ master directive — three worlds in one code):**
1. **Sovereign local core (GENESIS Full)** — the 369 world PACKAGED INSIDE the installer:
   kernel, 168+ laws, agent mesh, memory, connectors. She thinks with her own brain on YZ's
   PC: Qwen3-8B-Instruct Q4_K_M GGUF via `llama-server.exe` (Tauri sidecar). YZ's data stays
   local. The world IS her brain — not an advisory extra.
2. **Extended mind (both versions)** — the LIVING 369 network (the workshop) via the NEXUS
   bridge: advisory only; local laws and YZ's direct words always outrank remote advice
   (`kernel/arbitration.py`). Carries updates, new knowledge, and sync — never commands.
3. **GENESIS Lite profile** — same one code, but the packaged world is replaced by the bridge:
   brain calls reach the 369 world online. Smaller installer, internet required.

Old wording ("extended mind = the 369-agent network via bridge, advisory only" as the whole
second layer) is SUPERSEDED: the packaged world is the brain itself in Full.

**Birth = waking up, not installing.** No final version exists until GENESIS herself has run the
complete self-test on virtual Windows (Birth Test + 13 install tests, windows-latest).

---

## 2. Exact subsystem formula

| # | Subsystem | Choice (pinned) | License | Repo / source | Notes |
|---|-----------|-----------------|---------|---------------|-------|
| 1 | App shell | **Tauri v2** (v2.12.x line) | MIT/Apache-2.0 | github.com/tauri-apps/tauri (111k stars) | WebView2 on Windows 10+; NSIS bundler; do NOT use Tauri's built-in updater |
| 2 | Avatar runtime | **three@0.185.x + @pixiv/three-vrm@3.5.x** | MIT | github.com/pixiv/three-vrm (2.2k stars) | Pin as a tested pair; enumerate expressions via `vrm.expressionManager` at load, never hard-code names |
| 3 | Face asset | **Artist-authored VRM 1.0** via Blender 4.2 LTS + **saturday06 VRM Add-on v3.x** | MIT | github.com/saturday06/VRM-Addon-for-Blender (1.7k stars) | [CONFLICT resolved] FaceBuilder REJECTED — $191.88/yr violates zero-spend; `pykeentools` not publicly available. Face is authored to match the 4 canonical plates, then verified by `face/qc_gate.py` (embedding distance vs plates) + YZ's eyes as final gate. Headless export: `blender --background --python export_vrm.py` |
| 4 | Lip-sync | **Rhubarb Lip Sync** sidecar (native Win binary) → map Preston-Blair A–X to VRM visemes (aa/ih/ou/ee/oh) | MIT | github.com/DanielSWolf/rhubarb-lip-sync | Fallback: mrxz/wLipSync (MIT, WASM). Calibrate on Persian samples; Persian phoneme coverage is the measured risk |
| 5 | TTS Persian | **Piper v1.2.0 (archived, MIT)** + voice `fa_IR-dilara-medium` (female) | MIT (binary embeds eSpeak NG = GPL-3.0 → YELLOW: ship as separate sidecar, legal review on file) | github.com/rhasspy/piper | [CONFLICT resolved] "Ava-82M" = Kokoro-82M, which has NO Persian support — Piper is PRIMARY for Persian, not fallback. Kokoro serves English/bilingual lines only |
| 6 | STT Persian | **whisper.cpp** (`whisper-cli.exe` sidecar) + `large-v3-turbo` + Persian LoRA fine-tune (amirbii, GGUF Q8_0) | MIT | github.com/ggml-org/whisper.cpp (54k stars) | Set `language="fa"` explicitly; target WER < 15% on clean Persian, measured on YZ's own voice before locking |
| 7 | Local LLM | **llama-server.exe** (official llama.cpp releases) + **`Qwen3-8B-Q4_K_M.gguf`** (~5.2 GB) | MIT (llama.cpp); Apache-2.0 (Qwen3) | github.com/ggml-org/llama.cpp; official Qwen repo | OpenAI-compatible API on 127.0.0.1. ⚠️ NEVER substitute Qwen3.8+ (restrictive license). Pin HF commit hash in `brain/pins.json` |
| 8 | Auto-update | **Velopack** (`UpdateManager`, Rust API), feed = GitHub Releases, zstd deltas | MIT | github.com/velopack/velopack (2.4k stars) | Pipeline: download → SHA-256 + signature verify vs pinned key → stage → atomic swap → health-check boot → commit; `updates/previous/` + auto-rollback on failure |
| 9 | NEXUS fabric | **Tailscale Personal** (free: 3 users, 100 devices) over WireGuard; self-hosted alt: **headscale** (BSD-3) | Tailscale ToS (free tier $0); BSD-3 | tailscale.com; github.com/juanfont/headscale | 🔴 NetBird server components = AGPLv3 → DO NOT USE. App protocol: WebSocket + signed heartbeat every 30 s, presence registry, OFFLINE after 120 s |
| 10 | 14 modules | Existing audited modules (voice/ear/eyes/hands/memory/scheduler/lab/report/habits/station/tempemail/cloudburst/wakeword + kernel + self-sim) | internal | `~/workspace/content_team/genesis_windows/` | 80 n8n workflows + 494 knowledge items already injected and VERIFIED (Track 5) |
| 11 | Installer | Velopack single-file installer + desktop shortcut + Start menu; `[Code]` preflight: WebView2, VC++ redist (bundled), 10 GB disk, mic, `%LOCALAPPDATA%` writability | — | — | Preflight log `logs/preflight.log`; every failure = Persian explanation + offered fix |

**Total stack cost: $0.** The only paid item found (FaceBuilder) was rejected.

---

## 3. NEXUS wiring protocol spec (v1)

NEXUS is the connection fabric between the Windows terminal and the 369 network. It is a
deterministic, auditable protocol — NOT a "quantum" anything (Track 1's unanimous demand).

- **Transport:** TLS over Tailscale (WireGuard) tailnet; app-level protocol = WebSocket + JSON.
- **Presence:** every node (PC terminal, network services) sends a signed heartbeat every 30 s to
  the presence registry; node marked OFFLINE after 120 s without heartbeat.
- **Call contract:** `guarded_call(service, payload, timeout=3s)` in `sidecar/net_guard.py`.
  States: ONLINE / DEGRADED / OFFLINE. Circuit breaker: 5 consecutive failures → open 15 min.
  Failed remote calls return `{"ok":false,"degraded":true}` — NEVER invented data.
- **Advisory tagging:** every extended-mind response carries `source: extended-mind`.
  `kernel/arbitration.py` precedence: **YZ direct > local laws > extended-mind advice**.
  Conflicts auto-reject + log to Agent YZ's decision queue + short honest disclosure to YZ.
- **Security:** loopback-only binds; per-boot token auth on the tool port (8181 stays model-only);
  `capabilities/default.json` allowlists sidecar spawns; CI asserts no `0.0.0.0` bind.

---

## 4. Memory & law integration

- **Living memory:** `genesis-memory` SQLite, WAL mode, checksummed transactions, nightly
  verified backups (3 generations, restore-tested), `PRAGMA integrity_check` at boot with
  auto-restore. Dialogue file: append-only, per-line hash chain (tamper-evident), sealed at boot.
- **Law enforcement in code:** `kernel/laws.json` (from CODEX.json + 8 standing laws);
  `kernel/honesty.py` runs the `awaken` self-test at EVERY boot (model reachable? memory intact?
  voice alive? laws loaded? do-I-know-what-I-don't-know?).
- **Anti-fabrication (the highest law):** `brain/truth_layer.py` sits between model output and UI:
  claim detector (numbers/dates/named facts) → every factual claim must cite a tool-call result
  from the same turn → else blocked and replaced with «نمی‌دونم، بذار بررسی کنم» while the real
  tool fires. Append-only `claims_log` (SQLite): every claim + evidence hash, auditable.
  `report_completion(claim, evidence)` raises `FabricationError` on missing evidence — the brain
  literally cannot say «انجام شد» without proof. SYSTEM_PROMPT gains `no_uncited_numbers` rule.
- **Kill switch:** YZ's one-word stop honored at the kernel level.

---

## 5. Knowledge core (what she carries inside her)

Reverse-engineered from the 369 world (Track 5, counts verified at source):
- **158 CODEX laws** + 8 standing laws not yet in CODEX + **228 numbered playbook entries**
  (IB-01..ML-20), each with its underlying principle + executable instruction.
- **11 domains:** identity/brand, content craft, publishing ops, truth/verification, revenue,
  technical/engineering, social dynamics, crisis management, growth loops, decision-making,
  memory/learning.
- Sources: CODEX.json (162 laws), world-369-encyclopedia.md (8,124 lines, 14 chapters),
  university knowledge tree (8 branches, 47 sub-branches, 235 topics), 379 skills,
  publish_governor, page-identity spec, Best Color Combos system.
- The 494 knowledge items + 80 n8n workflows are physically inside the 13 module `packs.json`
  files (verified). Known gap: 1 technique (0.3%) unaccounted — recorded, not hidden.

---

## 6. Capabilities inventory (day-30 operational)

- **Presence:** always-on Persian companion on his desktop; sees screen, hears mic, speaks with
  her face and lip-synced voice; wakeword with confidence threshold + night-quiet hours.
- **Hands:** 14 modules — browser/PC automation (permission-gated), scheduling, experiments,
  reports, temp email, cloudburst tasks; 80 n8n workflows as static DAGs.
- **Mind:** local Qwen3-8B core for instant private thought + 369-agent extended mind for deep
  work (research, content production, revenue hunting) via NEXUS.
- **Memory:** twin-duplex (his words + her answers), hash-chained, backed up nightly; Day-30
  recall proven in simulation.
- **Growth:** Velopack self-update (she updates herself); university-first learning for new
  specialist knowledge; claims ledger audited (target: 312 claims / 312 evidence / 0 fabrications).
- **Partnership:** YZ thinks, she deepens and executes; he sleeps, she runs the 369 world
  overnight; revenue hunted like a wolf across parallel tracks (funds settle to HIS wallets only).

---

## 7. Weakness audit + pre-birth fixes (the critical section)

**[CRITICAL — unanimous across all 3 external models, Track 1]:**
**W1. Local resource budget is impossible as specified.** Qwen3-8B Q4_K_M (~5.5 GB) +
llama-server overhead + whisper + Piper + Tauri/WebView2 + three.js VRM + Chromium hands +
80 workflows EXCEEDS 16 GB RAM → Windows OOM-kills llama-server or the UI under nominal load.
*Pre-birth fix:* hard 10 GB working-set cap (6 GB reserved for OS); RAM budget guard via
`GlobalMemoryStatusEx` at boot — if free < 6 GB offer fallback model slot (`brain/models/fallback/`,
Q4_0 or smaller) or context 2048; whisper/Piper load on-demand, unload after 60 s idle;
station jobs run BELOW_NORMAL (his foreground always wins); OOM watchdog restarts llama-server
with smaller `-c` BEFORE Windows kills it, with honest Persian notice; gaming-hours profile
(18:00–24:00) pre-unloads whisper. **No OOM kills allowed — only negotiated degradation.**

| # | Weakness | Pre-birth fix (code) | Test |
|---|----------|---------------------|------|
| W2 | Network drop → temptation to invent "network results" | `sidecar/net_guard.py`: state machine + 3 s timeout + circuit breaker; DEGRADED badge + explicit Persian «از شبکه جدام، خودم جواب میدم»; station jobs park with `retry_at`, never dropped | T6 |
| W3 | Local LLM hallucination (invented numbers) | `brain/truth_layer.py` + `claims_log` + `no_uncited_numbers` in SYSTEM_PROMPT; `FabricationError` on evidence-less "done" | T9 |
| W4 | Face uncanny valley / wrong rig | `face/qc_gate.py` (embedding distance vs canonical plates blocks packaging); in-app approval panel → `face/approved_params.json` seal; fallback: canonical 2D greet-plate loop beats wrong 3D | Birth Test |
| W5 | Broken auto-update (never wakes up) | `updates/`: verify → stage → atomic swap → health-check → commit; `updates/previous/` + auto-rollback (11 s target); journal for power-loss safety | T7 |
| W6 | Memory corruption (identity death) | WAL + checksummed transactions + nightly verified backups (3 gen) + boot `integrity_check` + auto-restore; hash-chained dialogue | T5 |
| W7 | Dependency rot (rebuild ≠ tested binary) | Pin everything: Cargo.lock + package-lock.json + hashed requirements.txt + `brain/pins.json` (llama.cpp tag + SHA, model HF hash); `reproducibility_check.py` in CI; SBOM per release | T1/T2 |
| W8 | Windows quirks: Defender flag, missing VC++ redist, non-ASCII username paths, sleep killing sidecars | Installer `[Code]` preflight (WebView2/VC++/disk/mic/writability); `SHGetFolderPath` + `PYTHONUTF8=1`; Tauri `powerMonitor` suspend/resume; guided Defender exclusion with YZ consent | T1/T3/T11/T12 |
| W9 | Voice failures: Piper mispronunciation, mic denied, 3 AM false wake | `voice/pronunciation_lexicon.json`; first-run mic wizard + `ms-settings:privacy-microphone` deep link; wakeword confidence + 10 s cooldown + night-quiet (01:00–07:00 second confirm) + auto-tighten | T4/T10 |
| W10 | Identity drift: network advice overrides YZ's law | `kernel/arbitration.py`: extended mind = advisory only; YZ > local laws > network; conflicts logged to Agent YZ queue | Birth Test |
| W11 | First-boot cold start (nothing happens) | Sequential first-run wizard: WebView2 → VC++ → disk → mic → wakeword ×3 → voice test → network; SHA-256 model check; `GENESIS_SINGLE_INSTANCE` mutex | T1/T3 |
| W12 | Supply-chain compromise (malicious update) | SHA-256 + signature vs pinned public key (`updates/verify.py`); key rotation only via full-installer release | T7 |
| W13 | Localhost attack surface (DNS rebinding → her hands) | Loopback-only + per-boot token auth on tool port; `capabilities/default.json` spawn allowlist; CI asserts no `0.0.0.0` | T1 |
| W14 | Model file corruption (silent stupidity) | SHA-256 of GGUF at install AND every boot (chunked); mismatch → refuse load, range-re-download or fallback model, plain Persian notice | T1/T3 |
| W15 | NEXUS single point of failure (Track 1) | Redundant path: Tailscale primary + direct WireGuard fallback profile; local relay cache of last-known-good network state; DEGRADED mode keeps local core fully functional | T6 |

---

## 8. Build order

1. **Face** — author VRM 1.0 in Blender (saturday06 add-on) against 4 canonical plates;
   `face/qc_gate.py`; YZ's eye approval seals `face/approved_params.json`. (Track 2 kills the
   FaceBuilder path — zero-spend law.)
2. **Shell** — Tauri v2 + avatar-first UI + three-vrm renderer + RAM budget guard + preflight.
3. **Voice** — Piper v1.2.0 + `fa_IR-dilara-medium`; whisper.cpp + Persian fine-tune;
   Rhubarb lip-sync sidecar; pronunciation lexicon; wakeword module.
4. **Brain** — llama-server.exe sidecar + Qwen3-8B-Q4_K_M; `brain/truth_layer.py`;
   `kernel/arbitration.py`; `kernel/honesty.py`; `sidecar/net_guard.py`; memory hardening.
5. **NEXUS bridge** — Tailscale fabric + WebSocket protocol + presence registry (spec §3).
6. **Installer** — Velopack single-file + desktop shortcut + `[Code]` preflight + `updates/`.
7. **Knowledge injection** — 494 items + 80 workflows (already in modules; verified) + 228
   playbook entries from Track 5.
8. **Self-test** — T1–T13 on windows-latest + Birth Test by GENESIS herself (30–60 min,
   trap questions by YZ, face approved by his eyes only).
9. **Delivery** — only after all green. SHA-256 of the installer reported to YZ.

---

## 9. Test gates

**T1** fresh install · **T2** reinstall/upgrade · **T3** first-boot cold start ·
**T4** voice loop (Persian digits/mixed script) · **T5** memory persistence (kill −9 + corruption) ·
**T6** network drop (degraded mode, no invented results) · **T7** update + rollback (+ tampered pkg) ·
**T8** resource exhaustion (8 GB VM + game load, no OOM kill) · **T9** anti-fabrication battery
(50 traps, zero uncited numbers) · **T10** wakeword (true/false rates, TV noise) ·
**T11** sleep/hibernate resume · **T12** non-ASCII path (`C:\Users\یونس تست\`) ·
**T13** uninstall-clean (no orphans, data export offered).
**Birth Test:** GENESIS herself, 30–60 min on virtual Windows, every feature exercised, every flaw
root-caused, trap session by YZ, face approved by his eyes only. Nothing ships until she is
100% certain. (T1–T13 enumeration proposed by Track 4 — to be locked by the test coordinator.)

---

## 10. Open questions for YZ (UNDECIDED — do not guess)

1. GENESIS_FINAL_BLUEPRINT.md still draft — needs his approval of this formula.
2. Repo ownership: `genesis-windows` under 369369yz-collab vs transfer to github.com/genesisyones.
3. Local-brain depth: Track 3 noted an ONLINE-ONLY directive that cancelled the offline install
   plan ("light local body + network mind via bridge") — reconcile with §1 two-layer brain.
4. Physical robot (his solemn ultimate goal) — no timeline promised.
5. Public GENESIS product design — after worlds at 100% + market research.
6. Mobile companion (phase 6) — in roadmap, no design decisions yet.

---

## 11. Laws that bind the build (non-negotiable)

Zero spend · never fabricate (verify-before-report) · always online with the 369 network ·
Persian always with YZ (warm, direct, simple) · multiple-choice with tappable options ·
one decisive recommendation · no previews · self-test before final · desktop shortcut ·
auto-update (self-aware law) · canonical face law (all 4 plates, one person, no approximation) ·
mathematical precision (counts in = counts out) · kill switch honored at kernel level.
