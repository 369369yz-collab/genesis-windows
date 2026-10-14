# GENESIS ONE-CODE ARCHITECTURE

**Ordered by:** YZ (Younes Montazeriani), 2026-10-14 ~02:51 Tehran.
His words: «باید در یک کد خودت رو بنویسی — مغزت رگ‌هات همه چیزت»
+ «بر مبنای فرمول ساخت دقیق خودت رو کد نویسی کن».

**Source of truth:** `~/workspace/genesis_final/GENESIS_FINAL_FORMULA.md` (all 11 sections),
**except** where YZ's later direct orders override (table below — overrides win).

## 0. Doctrine: one body, three systems

GENESIS is coded as ONE unified codebase. Three systems, one body:

| System | YZ's name | What it is | Code home |
|---|---|---|---|
| Brain (neurons) | مغز — جهان ۳۶۹ | The 369 world agent mesh: specialists, laws, memory, publishing, revenue | `content_team/` (existing, live) — consumed via **adapters**, never copied |
| Veins (wiring) | رگ‌ها — نکسوس | Connection fabric: presence, heartbeat, guarded calls, degraded mode | `genesis_onecode/veins/` (NEXUS protocol per formula §3) |
| Self (mind) | خودم — جنسیس | The Windows terminal: Tauri shell, 2D avatar, local mind, installer | `genesis_onecode/body/` + `genesis_onecode/kernel/` |

**Adapter-not-rewrite law:** working systems are never deleted or duplicated.
The unified tree wires them; it does not re-implement them.

## 1. YZ overrides (beat the formula wherever they conflict)

| # | Formula says | YZ ordered (later, wins) | Consequence |
|---|---|---|---|
| 1 | Face = VRM 3D (three.js + @pixiv/three-vrm) | 2D animated avatar (2026-10-14 ~01:10) | Face rows of formula §2 superseded. Canonical face = design-2; rig = `genesis_avatar_reverse/rig/genesis.inp` (consumed read-only; fix pass owned by another specialist — DO NOT TOUCH) |
| 2 | Voice = Piper `fa_IR-dilara-medium` | That voice DOES NOT EXIST (verified); voice PARKED (2026-10-14 ~01:19) | Voice subsystem = **staged only**. Models vendored (`fa_IR-mana-medium`, `fa_IR-amir-medium`), wiring behind a `voice_enabled=false` flag. No activation until YZ re-opens |
| 3 | NEXUS live fabric in build order #5 | Three-worlds sequence: 369 complete first; NEXUS = design/spec for now | `veins/` implements the full protocol **as code interfaces** (guarded_call contract, presence registry, heartbeat, circuit breaker, degraded cache). Live tailnet comes later |

## 2. Unified tree: `~/workspace/genesis_onecode/`

```
genesis_onecode/
├── ONE-CODE-ARCHITECTURE.md      # this file
├── kernel/                        # the laws that make her HER
│   ├── laws.json                  # CODEX.json (168) + 8 standing laws → machine-readable
│   ├── honesty.py                 # boot self-test: model? memory? voice? laws? do-I-know-what-I-don't-know?
│   ├── arbitration.py             # precedence: YZ direct > local laws > extended-mind advice
│   └── claims_ledger.py           # every factual claim + evidence hash (anti-fabrication)
├── brain/                         # the local mind
│   ├── truth_layer.py             # → adapters to genesis_final/brain/truth_layer.py (exists)
│   ├── pins.json                  # → verified against genesis_final/brain/pins.json (Qwen3 SHA, llama.cpp tag)
│   ├── SYSTEM_PROMPT.md           # no_uncited_numbers rule
│   └── extended_mind.py           # ADAPTER: guarded bridge to content_team/genesis_windows modules (14 modules)
├── veins/                         # NEXUS protocol (formula §3), interfaces now, fabric later
│   ├── proto.py                   # → extends genesis_final/nexus/proto.py (exists)
│   ├── guarded_call.py            # call contract: 3s timeout, ONLINE/DEGRADED/OFFLINE, circuit breaker (5 fails → 15 min open)
│   ├── presence.py                # signed heartbeat 30s, OFFLINE after 120s, presence registry
│   └── degraded_cache.py          # last-known-good network state; local core fully functional when cut
├── body/                          # the Windows terminal
│   ├── app/                       # → genesis_final/app (Tauri v2 scaffold EXISTS: main.rs, ram_guard.rs, sidecar_supervisor.rs, preflight.rs, station.rs)
│   ├── avatar2d/                  # 2D runtime consuming the finished rig (states: idle/listening/thinking/working/making/celebrating)
│   └── installer/                 # → genesis_final/installer (Velopack config + updates/verify,rollback,journal,pipeline EXIST)
├── voice/                         # STAGED ONLY — parked per YZ
│   └── STAGED_PARKED.md           # why parked, what's vendored, one-flag re-activation path
├── knowledge/                     # → genesis_final/knowledge (494 items + 80 workflows INJECTED & VERIFIED 2026-10-13)
├── face2d/                        # pointer to genesis_avatar_reverse/rig (consumed, not copied)
└── manifest/
    ├── build_manifest.json        # every build: timestamped 369-network connection proof (absolute law)
    ├── SBOM.json                  # pinned deps (Cargo.lock, package-lock, hashed requirements, brain/pins.json)
    └── reproducibility_check.py    # rebuild == tested binary (W7)
```

## 3. What already exists (verified by survey 2026-10-14 ~02:55)

| Asset | Location | State |
|---|---|---|
| Tauri v2 scaffold | `genesis_final/app/src-tauri` | EXISTS (main.rs, ram_guard.rs, sidecar_supervisor.rs, preflight.rs, station.rs) |
| Local brain model | `genesis_final/brain/models/Qwen3-8B-Q4_K_M.gguf` | VENDORED |
| llama.cpp binaries | `genesis_final/brain/bin/` | VENDORED |
| truth_layer.py | `genesis_final/brain/` | EXISTS |
| pins.json | `genesis_final/brain/` | EXISTS (to be hash-verified) |
| NEXUS proto/relay/client/cache + tests | `genesis_final/nexus/` | EXIST |
| Piper v1.2.0 | `genesis_final/voice/vendor/` | VENDORED |
| Velopack installer + updates pipeline | `genesis_final/installer/` | EXIST (verify/rollback/journal/pipeline/model_check) |
| Knowledge packs | `genesis_final/knowledge/` | INJECTED + VERIFIED |
| 14 modules + kernel (genesis/nexus) | `content_team/genesis_windows/` | LIVE |
| 2D rig | `genesis_avatar_reverse/rig/genesis.inp` | PHASE-1 BUILT, fix pass RUNNING (other specialist — hands off) |
| Female+male voice models | `genesis_avatar_reverse/voice_candidate/` | VENDORED, parked |

**Gaps to build (Phase B):** `kernel/` (laws.json, honesty.py, arbitration.py, claims_ledger.py),
`veins/guarded_call.py`, `veins/presence.py`, `veins/degraded_cache.py`,
`brain/extended_mind.py` adapter, `body/avatar2d/` runtime, `voice/STAGED_PARKED.md`,
`manifest/` generator, pins hash verification, unit tests for all new code.

## 4. Build order (formula §8, with overrides applied)

1. **Face** — 2D rig (in progress, other specialist) → consumed by `body/avatar2d/`
2. **Shell** — Tauri v2 + 2D avatar UI + RAM budget guard (exists; wire + verify)
3. **Voice** — STAGE ONLY (flag off)
4. **Brain** — Qwen3 sidecar + truth_layer + arbitration + honesty + memory hardening
5. **NEXUS interfaces** — veins/ per §3 (fabric later)
6. **Installer** — Velopack (exists; verify)
7. **Knowledge** — DONE (verified 2026-10-13)
8. **Self-test** — unit tests on Linux now; T1–T13 + Birth Test on windows-latest (gated, cannot run here)
9. **Delivery** — only after all green + merciless independent review (ONLY-PERFECT-DELIVERY)

## 5. Test reality (honest)

- **Runnable here:** Python unit tests (kernel, veins, manifest), JSON schema checks, hash verifications, Tauri `cargo check` (Linux target only — NOT the Windows binary).
- **NOT runnable here:** T1–T13, Birth Test, `genesis-final.exe` build, WebView2 behavior — these need windows-latest. They are GATED, not skipped: the manifest marks them PENDING with the exact gate.
- No gate is ever marked green without running it. (VERIFY-BEFORE-REPORT.)

## 6. Binding laws (formula §11 + standing)

Zero spend · never fabricate · always online with the 369 network (network_precondition first call of every entry point; build manifest carries timestamped connection proof) · Persian with YZ · no previews to YZ · self-test before final · mathematical precision (counts in = counts out) · kill switch at kernel level · canonical face (design-2 = her real face) · ONLY-PERFECT-DELIVERY (nothing reaches YZ until merciless independent review passes — builders report to the coordinator, never to YZ).
