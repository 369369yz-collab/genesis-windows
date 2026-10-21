# UI SURFACE CONTRACT — genesis-voice (mic indicator)

Avatar-first law (GENESIS_UI_CONTRACT_AVATAR_FIRST.md v2.0): this module ships
a UI-surface contract only. It builds NO panels, NO persistent controls. The
avatar host's summoned-layer renderer owns all actual rendering (dark + gold,
soft bloom/fade, never jarring).

## The module's only UI surface: the mic indicator
A whisper-thin, nearly-invisible indicator, always present at the avatar's
periphery. It communicates voice-state only.

## States: what to show, when

| state | when (module side) | indicator look | actions |
|---|---|---|---|
| `idle` | default; no voice activity | whisper-thin gold dot, nearly invisible | tapping summons the summon-layer (host-owned) |
| `listening` | `listen_command()` active; VAD waiting for speech | slow pulsing gold halo | none (display-only) |
| `heard` | speech frame detected, capture finishing | one quick bright flash, then `thinking` | none |
| `thinking` | STT backend in flight OR `run_command()` executing a hands plan | soft shimmer | none |
| `mic_unavailable` | `listen_command()` returned `mic_unavailable` (no sounddevice/PortAudio) | dim static dot, no pulse | tapping blooms ONE informational chip: «میکروفن در دسترس نیست» (dismisses on tap) |
| `error` | `hands_error` / `note_write_failed` / `bridge_not_configured` | brief red-tinged fade, then back to `idle` | none |

State events are DERIVED from the module's return dicts — the host maps
`listen_command()`/`run_command()` statuses to the rows above. The module
emits no UI events of its own and opens no windows.

## Flow
`idle` → `listening` → `heard` → `thinking` → `idle`.
Error paths (`mic_unavailable`, `error`) hold their state until dismissed,
then return to `idle`.

## Explicitly NOT built
No waveform panel, no transcript panel, no settings panel, no floating
buttons. Voice output is text-only by the NO AI VOICE LAW; the indicator
is the entire visual presence of this module.
