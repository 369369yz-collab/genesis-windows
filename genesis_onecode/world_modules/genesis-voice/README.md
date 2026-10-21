# genesis-voice — Persian voice assistant (TEXT-FIRST)

Voice command pipeline for GENESIS: microphone -> transcription -> Persian
intent parsing -> execution via genesis-hands. **All output is text.**
There is no text-to-speech and no synthetic voice anywhere in this module —
voice synthesis is forbidden by standing law (NO AI VOICE LAW).

## What it does

1. `listen_command(timeout_s)` — records from the mic (sounddevice, 16kHz mono,
   VAD-gated: starts on first speech frame, stops after 1.2s trailing silence
   or the timeout) and sends the audio to the STT backend.
2. `parse_command(text_fa)` — rule-based Persian command parser returning a
   structured intent `{"action": ..., "params": {...}}`.
3. `run_command(text_fa)` — parse + execute: informational intents
   (time/date/note) are answered locally as text; action intents are converted
   to a genesis-hands plan and executed through it.

## Architecture

```
mic (sounddevice) ──► VAD-gated capture ──► PCM int16 @16kHz
                                                   │
                                                   ▼
                                          stt_backend()  ← BRIDGE CALL POINT
                                                   │  (injected; stubbed honestly)
                                                   ▼
                                          Persian transcript (str)
                                                   │
                                                   ▼
                                          parse_command() → {action, params}
                                                   │
                                   ┌───────────────┴───────────────┐
                                   ▼                               ▼
                          local text answer                 hands plan
                     (get_time/get_date/note)         → genesis_hands.execute()
```

## Bridge call points

- **`bridge_stt(audio_bytes, sample_rate=16000, language="fa")`** — the ONLY
  network-adjacent call point. Documented and stubbed: the stub returns
  `{"status": "bridge_not_configured", ...}` and **never fabricates a transcript**
  (no `"text"` key in the stub response). The real STT lives in the GENESIS
  bridge (network mind) and is injected at runtime:
  `VoiceAssistant(stt_backend=<callable>)`. Backend contract:
  `(audio_bytes: bytes, sample_rate: int, language: str) -> {"status": "ok", "text": str}`.
- **genesis-hands** — `_find_hands()` locates the sibling staging module
  (`../genesis-hands/hands.py`) or an installed `genesis_hands` package and
  calls its `execute(plan)`. When absent it returns
  `{"status": "hands_not_available", "intent": intent}` — the parsed intent is
  preserved, nothing is executed, nothing is faked.

## What's real vs what's stub

| Part | Status |
|---|---|
| Persian intent parser (regex rules) | Real. Covered by 25 tests. |
| Local intents: time, date, note-to-file | Real. Notes append to `genesis_notes.txt` (or injected path). |
| Intent -> hands plan mapping | Real plan dicts per the hands contract. |
| Mic capture (sounddevice) | Real when sounddevice + PortAudio exist; otherwise `{"status": "mic_unavailable"}` honestly. |
| STT transcription | **Stub.** On-device STT is out of scope; the bridge provides it. Stub never invents text. |
| genesis-hands execution | **Integration point.** Works when the sibling module exists; honest status when it doesn't. |
| TTS / voice output | **Deliberately absent.** Text-first by law. |

## Supported intents

| Persian example | action | params |
|---|---|---|
| ساعت چنده | get_time | — |
| امروز چه روزیه | get_date | — |
| باز کن notepad / notepad رو باز کن | open_app | {"app": "notepad"} |
| ببند notepad | close_app | {"app": "notepad"} |
| جستجو کن قیمت بیت کوین | web_search | {"query": "..."} |
| اسکرین شات / از صفحه عکس بگیر | screenshot | — |
| صدا رو زیاد کن / کم کن / بی صدا کن | volume | {"direction": "up"/"down"/"mute"} |
| یادداشت کن فردا جلسه | note | {"text": "..."} |
| قفل کن | lock_screen | — |
| anything else | unknown | {"raw": text} — honest, never guessed |

## Windows-only notes

- Target: Windows 10/11, Python 3.12, bundled venv.
- `sounddevice` needs the **PortAudio** native library (ships with the installer).
- `genesis-hands` performs the Windows actions (pywinauto local, Playwright web);
  this module only builds the plan dicts and is OS-agnostic.

## API reference

```python
from voice_assistant import VoiceAssistant, parse_command, bridge_stt

va = VoiceAssistant()  # or VoiceAssistant(stt_backend=real_stt, notes_path="...")

va.listen_command(timeout_s=8.0)  # {"status": "ok", "text": "..."} | mic_unavailable |
                                  # bridge_not_configured | no_speech
parse_command("ساعت چنده")        # {"status": "ok", "intent": {"action": "get_time", ...}}
va.run_command("باز کن notepad")  # {"status": "ok", "response": "برنامه‌ی ...", ...}
```

All public functions return plain dicts with a `"status"` key. `run_command`
always includes a `"response"` string — that is the text shown to father.

## Running tests

```
python -m pytest tests/ -q
python windows_smoke_test.py
```
