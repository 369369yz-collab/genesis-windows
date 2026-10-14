# VOICE — STAGED ONLY (parked per YZ direct order)

**Status: PARKED. Not active. Not wired into the runtime.**

## Why parked

YZ direct order, 2026-10-14 ~01:19 Tehran — his words: «فعلا نیاز نیست برات صدا بزاریم»
("no need to put voice on it for now"). Voice work is deferred by his explicit
decision. Focus is the animated 2D avatar (rig in progress). Nothing in this
directory may be activated, wired, or demoed until YZ re-opens voice himself.

Related history (verified):
- 2026-10-14 ~01:12: the formula's `fa_IR-dilara-medium` voice DOES NOT EXIST —
  all 5 upstream Piper `fa_IR` voices are male. I wrongly told YZ dilara was
  chosen; corrected honestly the same night.
- 2026-10-14 ~01:15: YZ ordered a custom female Persian voice
  («صدای زن سفارشی بساز»).
- 2026-10-14 ~01:17: female voice FOUND + verified on this VM —
  MahtaFetrat/Mana-Persian-Piper (`fa_IR-mana-medium.onnx`), MIT license,
  single female speaker. Synthesizes Persian, RTF 0.10 (~10x realtime on CPU),
  median F0 ~232 Hz (female band; upstream male voices 94–146 Hz). Drop-in
  ONNX replacement. YZ listening QC of the greeting sample was pending when
  voice was parked — the sample is staged below, not sent.

## What's vendored (verified on disk 2026-10-14)

| Asset | Path | State |
|---|---|---|
| Female voice model | `~/workspace/genesis_avatar_reverse/voice_candidate/fa_IR-mana-medium.onnx` (+ `.onnx.json`) | vendored, tested |
| Male voice model | `~/workspace/genesis_final/voice/models/fa_IR-amir-medium.onnx` (+ `.onnx.json`) | vendored |
| Piper engine | `~/workspace/genesis_final/voice/vendor/piper-v1.2.0/` (+ `piper_v1.2.0_amd64.tar.gz`) | vendored |
| Rhubarb lip-sync | `~/workspace/genesis_final/voice/vendor/rhubarb-1.14.0/` (+ `rhubarb_1.14.0_linux.zip`) | vendored, staged hook only |
| Greeting samples | `~/workspace/genesis_avatar_reverse/voice_candidate/{mana_greeting,mana_speed,mana_test,amir_greeting}.wav` | staged, not sent to YZ |

NOTE (honest correction): an earlier note placed `fa_IR-amir-medium.onnx` in
`voice_candidate/` — it is NOT there. It lives at
`~/workspace/genesis_final/voice/models/fa_IR-amir-medium.onnx`. The
`voice_candidate/` dir holds only the Mana model + the four `.wav` samples
(`amir_greeting.wav` is a sample, not the model).

## One-flag re-activation path

Voice is behind a single flag: `voice_enabled` in
`~/workspace/genesis_onecode/voice/voice_config.json` (default `false`).

To re-activate (only on YZ's explicit re-open):
1. Set `"voice_enabled": true` in `voice_config.json`.
2. Point the engine at the vendored Piper binary + chosen ONNX model
   (default: `fa_IR-mana-medium`, the verified female voice).
3. Register the Rhubarb backend with the avatar2d lip-sync hook
   (`body/avatar2d/avatar2d.js` → `registerLipSyncHook` / `feedMouthOpen`
   → drives `ParamMouthOpenY` + the rig's `talk` animation).
4. Slot the Piper sidecar into the Tauri `SidecarSupervisor`
   (60 s idle unload policy already in `genesis_final/app/src-tauri`).
5. Re-run the voice test battery (T4: Persian digits/mixed script;
   T10: wakeword true/false rates) on windows-latest before any demo.

Until then: staged, silent, zero spend, no activation.
