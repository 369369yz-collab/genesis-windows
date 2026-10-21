# genesis-wakeword

On-device wake-word detector for GENESIS. CPU-friendly, no GPU, no network calls.

## What it does

Listens to the microphone (or a provided audio stream) and calls `on_wake()`
when it hears the enrolled keyword (default: "genesis"). Enrollment is required:
the user speaks the keyword 3+ times, `enroll()` builds an energy/ZCR contour
template, and detection compares incoming speech segments against that template.

Two-stage pipeline:
1. **VAD** — `webrtcvad` on 20ms frames (falls back to a pure-Python energy VAD
   if webrtcvad is not installed).
2. **Template matching** — a speech segment's log-energy + zero-crossing-rate
   contour is length-normalized, gain-normalized, and compared to the template
   with cosine similarity. Similarity >= `threshold` (default 0.72) fires `on_wake`.

## Architecture

```
mic (sounddevice 16kHz mono) ──► 20ms frames ──► webrtcvad ──► speech segments
        (or iterable of int16 chunks for tests)        │
                                                      ▼
                                        energy/ZCR contour → normalize → resample
                                                      │
                                                      ▼
                                        cosine similarity vs enrolled template
                                                      │ >= threshold
                                                      ▼
                                                   on_wake()
```

`_MicStreamer` bridges sounddevice callbacks into the frame loop.
`_listen_stream` is source-agnostic, which is how the whole detector is tested
without a microphone.

## Bridge call points

**None.** This module is fully on-device by design and makes zero network calls.

## What's real vs what's stub

| Part | Status |
|---|---|
| VAD (webrtcvad) | Real. Optional dependency; honest energy fallback when absent. |
| Enrollment + template save/load (JSON) | Real. |
| Contour similarity detection | Real algorithm (CPU), but see accuracy limits below. |
| Mic capture (sounddevice) | Real when sounddevice + PortAudio are installed; otherwise `listen()` returns `{"status": "mic_unavailable"}` honestly. |
| Neural wake-word model | **Not present.** No model file is shipped or faked. |

## Accuracy limits (read before trusting it)

- This is **energy-contour matching, not phonetic recognition**. It answers
  "does this sound like the enrolled utterance?" — a similar-length, similar-energy
  utterance can false-positive; a hoarse/whispered keyword can false-negative.
- Enrollment is mandatory and speaker-specific. No universal "genesis" model.
- Works best in quiet rooms, close mic, consistent speaking pace.
- Threshold default 0.72; raise it to reduce false positives, lower it to reduce
  misses. Tune per environment.
- VAD hangover (webrtcvad flags a few silence frames after speech) is handled by
  energy-based trailing trim in `_trim()`.

## Upgrade path (documented, not implemented)

Replace the contour matcher with a neural keyword spotter:
1. Train or download an **openWakeWord**-compatible ONNX model for "genesis"
   (openWakeWord is MIT-licensed; community models exist).
2. Add `onnxruntime` to requirements, load the model in `WakeWordDetector`,
   and feed it the same 16kHz frames in `_handle_segment`.
3. Keep `enroll()` as a fallback path, or remove it once the model is validated.

No fake `.onnx`/`.tflite` file is bundled — a placeholder model would be worse
than none, because it would silently not detect.

## Windows-only notes

- Target: Windows 10/11, Python 3.12, bundled venv.
- `sounddevice` needs the **PortAudio** native library. On the Windows build it
  ships with the installer; on a dev machine install it via the OS package
  manager (`apt install portaudio19-dev`, `brew install portaudio`).
- No Windows-only API is used; the module runs identically on Linux for dev.

## API reference

```python
from wakeword import WakeWordDetector

det = WakeWordDetector(keyword="genesis", on_wake=lambda: print("WAKE"),
                       threshold=0.72, vad_aggressiveness=2)

det.enroll([utt1, utt2, utt3])   # int16 np arrays @16kHz -> {"status": "ok", ...}
det.score(pcm)                   # {"status","similarity","detected","threshold"}
det.save_template("kw.json")     # -> {"status": "ok", "path": ...}
det.load_template("kw.json")     # -> {"status": "ok", "keyword": ...}
det.listen()                     # blocks; mic. -> {"status": "stopped", ...}
det.listen(source=chunks_iter)   # simulated stream (tests)
det.stop()                       # -> {"status": "stopped"}
det.enrolled                     # bool
det.vad_implementation           # "webrtcvad" | "energy_fallback"
```

All public methods return plain dicts with a `"status"` key.

## UI surface (avatar-first law)

This module's only UI surface is the whisper-thin **mic indicator**, per
`_contracts/GENESIS_UI_CONTRACT_AVATAR_FIRST.md`. No panels are ever built here;
floating-layer rendering belongs to the avatar host's summoned-layer renderer.

```python
det.ui_surface()   # {"module","surface":"mic_indicator","allowed_states",
                   #  "current_state","state_meaning","rendering"}
```

States: `idle` (not listening) → `listening` (monitoring stream) →
`heard` (keyword just detected, `on_wake` fired) → host takes over.
`thinking` is host-owned (the mind's turn after a wake); this module never sets it.

## Running tests

```
python -m pytest tests/ -q
python windows_smoke_test.py
```
