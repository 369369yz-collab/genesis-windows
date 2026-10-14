# GENESIS — Two Versions Spec
**Ordered by YZ 2026-10-14 ~05:21 Tehran («دو نسخه درست کن»). Resolves the online-vs-local contradiction.**

## Version 1 — GENESIS Lite (سبک / آنلاین)
- Small installer (target: under ~150 MB, no local AI model, no bundled Chromium).
- Face: VOID frontend (Tauri 2 shell).
- Brain: ONLINE — connects to the 369 world (kernel + laws + agents run remotely, reached through the veins protocol).
- Browser: uses the OS default browser via automation hooks (no portable Chromium bundled); governor still enforces session limits.
- Memory: local SQLite for personal memory; world memory stays remote.
- Requires: internet connection, always.
- Use case: quick install, light PCs, always-connected users.

## Version 2 — GENESIS Full (کامل / مستقل) — PRIMARY
- Full installer (target: several GB — includes everything below).
- Face: VOID frontend (Tauri 2 shell) — same face module, one code.
- Brain: the 369 world PACKAGED INSIDE — agents, 168+ laws, kernel, memory, connectors run locally on the PC.
- Local AI model on GPU (RTX 5070 12GB target — quantized ~12B class; exact model chosen in the model-selection step).
- Portable Chromium bundled INSIDE the installer + Browser Governor (session queue, concurrency cap, RAM/CPU guard, approval gate for sensitive actions, quarantine for downloads, per-agent profiles).
- Memory: local SQLite (personal) + packaged world memory; optional sync with the workshop.
- Requires: nothing — works fully offline; online features (world sync, updates) are optional.
- Use case: YZ's PC — the real GENESIS. Independent and online-capable, exactly the master directive.

## Shared (both versions)
- One codebase (genesis_onecode): face + brain(369) + veins(nexus) + kernel. Lite and Full are BUILD PROFILES, not forks.
- VOID face design; Persian-first UI; no decorative/non-working controls.
- Kill-switch, honesty layer, claims ledger in both.
- Voice: parked (YZ order) in both until he re-enables.

## Definition of done (per version)
- Real Tauri build on windows-latest CI → installer artifact with SHA-256.
- Install + launch on clean Windows VM → T1–T13 suite green ×3.
- GENESIS 30–60 min self birth-test on the final build.
- YZ hands-on test.
- Lite must prove: online brain reachable, graceful offline degradation message (honest, never fake).
- Full must prove: zero network needed for core loop (chat → think → act → remember), browsers open invisibly and do real work.
